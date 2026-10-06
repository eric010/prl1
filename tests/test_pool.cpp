#include "cp_pool.h"
#include "cp_util.h"
#include "cp_state.h"
#include "cp_job_ctrl.h"
#include "cp_fee.h"
#include "json.hpp"
#include <cassert>
#include <cstring>
#include <iostream>
#include <thread>
#include <chrono>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
using J=nlohmann::json;
static J job() {return {{"method","mining.notify"},{"params",{{"header",std::string(152,'0')},{"target",std::string(64,'f')},{"job_id","local-test"},{"cert_version",3}}}};}
static bool parse(const J& j) {
 char id[128],hdr[153],target[65];uint32_t cv;
 return cp_pool_parse_notify(j.dump().c_str(),id,sizeof(id),hdr,sizeof(hdr),target,sizeof(target),&cv)!=0;
}
static std::string line(int s) {
 std::string b;char ch;
 while(recv(s,&ch,1,0)==1){if(ch=='\n')return b;b+=ch;}
 throw std::runtime_error("socket closed");
}
static void sendline(int s,const J& j) {assert(cp_send_json(s,j.dump().c_str()));}
int main() {
 setenv("PRL_WORKDIR","/tmp/prl-workdir-unit-test",1);
 cp_init_workdir();assert(std::string(g_workdir)=="/tmp/prl-workdir-unit-test");
 unsetenv("PRL_WORKDIR");
 auto j=job();assert(parse(j));
 for(const char* name:{"target","header","job_id","cert_version"}){auto x=j;x["params"].erase(name);assert(!parse(x));}
 auto x=j;x["params"]["cert_version"]=4;assert(!parse(x));
 x=j;x["params"]["target"]=std::string(64,'0');assert(!parse(x));
 x=j;x["params"]["target"]=std::string(64,'z');assert(!parse(x));
 x=j;x["params"]["header"]=std::string(160,'0');assert(!parse(x));
 x=j;x["params"]["job_id"]=std::string(128,'a');assert(!parse(x));
 // Header bytes beyond the old 8-byte prefix, target and cert all invalidate work.
 uint8_t h[76]={};uint32_t t[8]={1};char k0[320],k1[320];
 cp_make_job_key("same-id",h,t,3,k0);
 h[75]=1;cp_make_job_key("same-id",h,t,3,k1);assert(strcmp(k0,k1));h[75]=0;
 t[7]=1;cp_make_job_key("same-id",h,t,3,k1);assert(strcmp(k0,k1));t[7]=0;
 cp_make_job_key("same-id",h,t,2,k1);assert(strcmp(k0,k1));
 cp_fee_init("test-user",1);cp_fee_set_tiles_per_matrix(100);
 for(int i=0;i<1000;i++){cp_fee_note_tiles(1000000);cp_fee_prepare_matrix();assert(!cp_fee_needs_switch());}
 assert(!cp_fee_enabled());assert(std::string(cp_fee_wallet())=="test-user");
 // Socket test against localhost ONLY. No real pool, wallet or proof submission.
 int s=socket(AF_INET,SOCK_STREAM,0);assert(s>=0);
 sockaddr_in a{};a.sin_family=AF_INET;a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);a.sin_port=0;
 assert(bind(s,(sockaddr*)&a,sizeof(a))==0);assert(listen(s,1)==0);
 socklen_t alen=sizeof(a);assert(getsockname(s,(sockaddr*)&a,&alen)==0);
 std::thread server([&]{
   int p=accept(s,nullptr,nullptr);assert(p>=0);
   auto auth=J::parse(line(p));assert(auth["params"]["wallet"]=="user\"escaped");assert(auth["params"]["pass"]=="d=2097152");
   // A notify can arrive before auth, split across TCP packets, with braces in a string.
   auto n=job();n["params"]["job_id"]="job{with}braces";
   auto wire=n.dump()+"\n";assert(send(p,wire.data(),13,0)==13);
   std::this_thread::sleep_for(std::chrono::milliseconds(20));
   assert(send(p,wire.data()+13,wire.size()-13,0)==ssize_t(wire.size()-13));
   sendline(p,{{"id",1},{"result",true},{"error",nullptr}});
   auto submit=J::parse(line(p));assert(submit["id"]==2);assert(submit["params"]["plain_proof"]=="LOCAL_TEST_NOT_A_PROOF");
   sendline(p,{{"id",999},{"result",true}}); // never count unrelated acks
   sendline(p,{{"id",2},{"result",false},{"error",{{"code",23}}}});
   submit=J::parse(line(p));assert(submit["id"]==3);
   sendline(p,{{"id",3},{"result",true},{"error",nullptr}});
   // Incomplete JSON must not prevent bounded reader_stop.
   send(p,"{\"id\":",6,0);
   std::this_thread::sleep_for(std::chrono::milliseconds(700));close(p);
 });
 assert(cp_pool_connect("127.0.0.1",ntohs(a.sin_port))==1);
 strcpy(password_global,"d=2097152");
 assert(cp_pool_send_authorize(1,"user\"escaped","rig","test-agent"));cp_pool_reader_start();
 char buf[65536];assert(cp_pool_wait_line(buf,sizeof(buf),2000)==1);assert(parse(J::parse(buf)));
 assert(cp_pool_send_plain_proof_submit(cp_pool_socket(),2,"job{with}braces","LOCAL_TEST_NOT_A_PROOF",1));
 assert(cp_pool_send_plain_proof_submit(cp_pool_socket(),3,"job{with}braces","LOCAL_TEST_NOT_A_PROOF",1));
 std::this_thread::sleep_for(std::chrono::milliseconds(200));
 auto before=std::chrono::steady_clock::now();cp_pool_reader_stop();
 assert(std::chrono::steady_clock::now()-before<std::chrono::seconds(1));
 cp_pool_disconnect();server.join();close(s);
 assert(cp_pool_connect("127.0.0.1",ntohs(a.sin_port))==0);cp_pool_disconnect();
 std::cout<<"Protocol, job fingerprints, fee and reconnect tests: PASS\n";
}
