// PRL3060 Kryptex experimental transport, MIT. Linux/TCP only.
#include "cp_pool.h"
#include "cp_job_ctrl.h"
#include "cp_state.h"
#include "cp_util.h"
#include "json.hpp"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <stdexcept>
#include <cerrno>
#include <fcntl.h>
#include <netdb.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

using Json = nlohmann::json;
static int sockfd = -1;
static std::atomic<bool> running{false}, lost{false}, authorized{false};
static std::atomic<double> difficulty{2097152.0};
static std::thread reader;
static std::mutex tx_mx, inbox_mx, pending_mx;
static std::condition_variable inbox_cv;
static std::deque<std::string> inbox;
static std::set<int> submissions;
static int auth_id = -1;
static std::mutex latest_mx;
static std::string latest_key;
static CpPendingJob pending{};
static bool pending_valid = false;
static const size_t MAX_FRAME = 65535;

static void event(const Json& v) {
    std::string s = v.dump();
    printf("[prl-event] %s\n", s.c_str()); fflush(stdout);
}
static bool hex_valid(const std::string& s, size_t n) {
    return s.size()==n && s.find_first_not_of("0123456789abcdefABCDEF")==std::string::npos;
}
static bool valid_notify(const Json& j) {
    if(!j.is_object() || j.value("method",std::string())!="mining.notify") return false;
    if(!j.contains("params") || !j["params"].is_object()) return false;
    const auto& p=j["params"];
    for(const auto* k: {"header","target","job_id"})
        if(!p.contains(k) || !p[k].is_string()) return false;
    const auto h=p["header"].get<std::string>(), t=p["target"].get<std::string>();
    const auto id=p["job_id"].get<std::string>();
    if(!hex_valid(h,152) || !hex_valid(t,64) || t.find_first_not_of('0')==std::string::npos) return false;
    if(id.empty() || id.size()>127 || id.find('\0')!=std::string::npos) return false;
    // Unknown consensus versions must never be treated as v3 silently.
    if(!p.contains("cert_version") || !p["cert_version"].is_number_integer()) return false;
    int v=p["cert_version"].get<int>(); return v>=1 && v<=3;
}
int cp_pool_parse_notify(const char* line, char* id,int ilen,char* hdr,int hlen,
                        char* target,int tlen,uint32_t* cert) {
    if(!id || !hdr || !target || ilen<1 || hlen<1 || tlen<1) return 0;
    id[0]=hdr[0]=target[0]=0;
    try {
        Json j=Json::parse(line);
        if(!valid_notify(j)) return 0;
        const auto& p=j["params"];
        auto a=p["job_id"].get<std::string>(), b=p["header"].get<std::string>(), c=p["target"].get<std::string>();
        if(a.size()>=size_t(ilen) || b.size()>=size_t(hlen) || c.size()>=size_t(tlen)) return 0;
        strcpy(id,a.c_str());strcpy(hdr,b.c_str());strcpy(target,c.c_str());
        if(cert) *cert=p["cert_version"].get<uint32_t>();
        return 1;
    } catch(...) { return 0; }
}
static void dispatch_job(const Json& j) {
    CpPendingJob p{}; char hdr[153];
    const auto line=j.dump();
    if(!cp_pool_parse_notify(line.c_str(),p.job_id,sizeof(p.job_id),hdr,sizeof(hdr),
                            p.target_hex,sizeof(p.target_hex),&p.cert_version))
        throw std::runtime_error("unsupported or invalid mining.notify");
    cp_hex_to_bytes(hdr,p.header,76);
    if(!cp_be_target_hex_to_le_words(p.target_hex,p.tgt)) throw std::runtime_error("invalid target");
    cp_make_job_key(p.job_id,p.header,p.tgt,p.cert_version,p.job_key);
    {std::lock_guard<std::mutex> lk(latest_mx);latest_key=p.job_key;}
    // Queue every update in the inbox. The mining thread consumes it after its
    // current attempt is cancelled; this avoids an active/idle handoff race.
    if(cp_job_mining_active()) {
        if(cp_job_key_matches(p.job_key)) return;
        cp_job_request_cancel();
    }
    {
        std::lock_guard<std::mutex> lk(inbox_mx);
        inbox.clear(); inbox.push_back(line);
    }
    inbox_cv.notify_all();
    event({{"type","job"},{"cert_version",p.cert_version}});
}
static int tcp_connect(const char* host,int port) {
    addrinfo hints{}, *res=nullptr; hints.ai_socktype=SOCK_STREAM; hints.ai_family=AF_UNSPEC;
    const auto ps=std::to_string(port);
    if(getaddrinfo(host,ps.c_str(),&hints,&res)!=0) return -1;
    int chosen=-1;
    for(auto p=res;p;p=p->ai_next) {
        int s=socket(p->ai_family,p->ai_socktype,p->ai_protocol); if(s<0) continue;
        int flags=fcntl(s,F_GETFL,0); fcntl(s,F_SETFL,flags|O_NONBLOCK);
        int rc=connect(s,p->ai_addr,p->ai_addrlen);
        if(rc<0 && errno==EINPROGRESS) {
            pollfd f{s,POLLOUT,0}; rc=poll(&f,1,10000);
            int err=0; socklen_t len=sizeof(err);
            if(rc>0 && getsockopt(s,SOL_SOCKET,SO_ERROR,&err,&len)==0 && err==0) rc=0; else rc=-1;
        }
        if(rc==0) {
            fcntl(s,F_SETFL,flags);
            timeval tv{10,0};setsockopt(s,SOL_SOCKET,SO_SNDTIMEO,&tv,sizeof(tv));
            int on=1;setsockopt(s,SOL_SOCKET,SO_KEEPALIVE,&on,sizeof(on));
            chosen=s;break;
        }
        close(s);
    }
    freeaddrinfo(res);return chosen;
}
int cp_pool_connect(const char* host,int port) {
    {std::lock_guard<std::mutex> lk(latest_mx);latest_key.clear();}
    sockfd=tcp_connect(host,port); lost.store(sockfd<0); authorized.store(false);
    return sockfd>=0 ? 1:0;
}
int cp_pool_socket(void) { return sockfd; }
void cp_pool_reader_stop(void) {
    running.store(false);
    // poll is bounded, so no blocking recv holds shutdown hostage.
    if(reader.joinable()) reader.join();
}
void cp_pool_disconnect(void) {
    cp_pool_reader_stop();
    std::lock_guard<std::mutex> tx(tx_mx);
    if(sockfd>=0) { close(sockfd);sockfd=-1; }
    submissions.clear();auth_id=-1;authorized.store(false);
    std::lock_guard<std::mutex> lk(pending_mx);pending_valid=false;
}
int cp_pool_send_authorize(int id,const char* wallet,const char* worker,const char* agent) {
    Json j={{"id",id},{"method","mining.authorize"},{"params",{{"wallet",wallet},{"worker",worker},{"pass",password_global},{"agent",agent}}}};
    std::lock_guard<std::mutex> lk(tx_mx); auth_id=id;
    return cp_send_json(sockfd,j.dump().c_str());
}
int cp_pool_send_plain_proof_submit(int sock,int id,const char* job,const char* proof,double hs) {
    if(!authorized.load() || sock!=sockfd || lost.load() || cp_job_should_cancel()) return 0;
    Json j={{"id",id},{"method","mining.submit"},{"params",{{"job_id",job},{"plain_proof",proof},{"hs",hs}}}};
    std::lock_guard<std::mutex> lk(tx_mx);
    if(submissions.size()>=128) { lost.store(true); cp_job_request_cancel(); return 0; }
    submissions.insert(id);
    int ok=cp_send_json(sockfd,j.dump().c_str());
    if(!ok) { submissions.erase(id);lost.store(true);cp_job_request_cancel(); }
    else event({{"type","submitted"},{"id",id}});
    return ok;
}
static void read_loop() {
    std::string buffer;Json early, last_job;
    auto last_rx=std::chrono::steady_clock::now();
    try {
        while(running.load() && !lost.load()) {
            pollfd f{sockfd,POLLIN,0};int rc=poll(&f,1,200);
            if(rc<0 && errno==EINTR) continue;
            if(rc<0) throw std::runtime_error("poll failed");
            if(rc==0) {
                if(std::chrono::steady_clock::now()-last_rx>std::chrono::seconds(180))
                    throw std::runtime_error("pool silent for 180 seconds");
                continue;
            }
            char chunk[8192];auto n=recv(sockfd,chunk,sizeof(chunk),MSG_DONTWAIT);
            if(n<0 && (errno==EAGAIN || errno==EINTR)) continue;
            if(n<=0) throw std::runtime_error("pool disconnected");
            buffer.append(chunk,size_t(n));last_rx=std::chrono::steady_clock::now();
            size_t pos;
            while((pos=buffer.find('\n'))!=std::string::npos) {
                if(pos>MAX_FRAME) throw std::runtime_error("pool frame too large");
                std::string line=buffer.substr(0,pos);buffer.erase(0,pos+1);
                if(line.empty() || line=="\r") continue;
                Json j=Json::parse(line);
                if(!j.is_object()) throw std::runtime_error("pool JSON must be an object");
                const auto method=j.value("method",std::string());
                if(method=="mining.notify") {
                    if(!valid_notify(j)) throw std::runtime_error("unsupported job or certificate version");
                    last_job=j;
                    if(authorized.load()) dispatch_job(j); else early=j;
                } else if(method=="mining.set_target") {
                    if(last_job.is_null()) throw std::runtime_error("target without job");
                    const auto p=j.at("params");
                    std::string t=p.is_array()?p.at(0).get<std::string>():p.at("target").get<std::string>();
                    last_job["params"]["target"]=t;
                    if(authorized.load()) dispatch_job(last_job);else early=last_job;
                } else if(method=="mining.set_difficulty") {
                    // Pearl pool difficulty units differ; the next explicit target
                    // is required. Stop old work instead of guessing a threshold.
                    cp_job_request_cancel();
                    event({{"type","await_target"}});
                } else if(method.empty() && j.contains("id") && j["id"].is_number_integer()) {
                    int id=j["id"].get<int>();
                    bool ok=j.contains("result") && j["result"].is_boolean() && j["result"].get<bool>() && (!j.contains("error") || j["error"].is_null());
                    bool is_auth=false,is_share=false;
                    {std::lock_guard<std::mutex> lk(tx_mx);is_auth=id==auth_id;is_share=submissions.erase(id)>0;}
                    if(is_auth) {
                        event({{"type","authorized"},{"ok",ok}});
                        if(!ok) throw std::runtime_error("pool authorization rejected");
                        authorized.store(true);
                        if(!early.is_null()){dispatch_job(early);early=nullptr;}
                    } else if(is_share) {
                        int code=0;
                        if(j.contains("error") && j["error"].is_object() && j["error"].contains("code") && j["error"]["code"].is_number_integer()) code=j["error"]["code"].get<int>();
                        event({{"type","share"},{"id",id},{"accepted",ok},{"error_code",code}});
                    }
                }
            }
            if(buffer.size()>MAX_FRAME) throw std::runtime_error("unterminated pool frame too large");
        }
    } catch(const std::exception& e) {
        fprintf(stderr,"[net] %s\n",e.what());fflush(stderr);
    }
    lost.store(true);authorized.store(false);cp_job_request_cancel();inbox_cv.notify_all();
    event({{"type","disconnected"}});
}
void cp_pool_reader_start(void) {
    if(running.exchange(true)) return;
    lost.store(false);reader=std::thread(read_loop);
}
void cp_pool_inbox_clear(void) {std::lock_guard<std::mutex> lk(inbox_mx);inbox.clear();}
int cp_pool_wait_line(char* out,size_t cap,int ms) {
    std::unique_lock<std::mutex> lk(inbox_mx);
    auto ready=[](){return !inbox.empty() || lost.load();};
    if(ms<0) inbox_cv.wait(lk,ready);
    else if(!inbox_cv.wait_for(lk,std::chrono::milliseconds(ms),ready)) return 0;
    if(lost.load()) return -1;
    auto line=inbox.back();inbox.clear();
    if(line.size()>=cap) return -1;
    memcpy(out,line.c_str(),line.size()+1);return 1;
}
int cp_pool_conn_lost(void) {return lost.load();}
void cp_pool_set_submit_inflight(int) {}
void cp_pool_log_share_submit_outcome(void) {}
int cp_pool_take_pending_job(CpPendingJob*) {return 0;} // updates use the single inbox
void cp_pool_set_difficulty(double d) {if(d>0) difficulty.store(d);}
double cp_pool_difficulty(void) {return difficulty.load();}

int cp_pool_job_matches(const char* key) {
    std::lock_guard<std::mutex> lk(latest_mx);
    return latest_key.empty() || latest_key==key;
}
