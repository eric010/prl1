// PRL3060: no developer-fee destination or scheduling. CPPminer MIT fork.
#include "cp_fee.h"
#include <cstring>
static char wallet[256] = {};
static uint64_t tiles = 0;
void cp_fee_init(const char* s, int) { std::strncpy(wallet,s,255); wallet[255]=0; }
void cp_fee_set_tiles_per_matrix(uint64_t t) { tiles=t; }
void cp_fee_on_authorized(void) {}
const char* cp_fee_wallet(void) { return wallet; }
void cp_fee_prepare_matrix(void) {}
int cp_fee_next_is_dev(void) { return 0; }
int cp_fee_needs_switch(void) { return 0; }
void cp_fee_note_tiles(uint64_t) {}
uint64_t cp_fee_debt(void) { return 0; }
uint64_t cp_fee_tiles_per_matrix(void) { return tiles; }
uint64_t cp_fee_threshold(void) { return 0; }
int cp_fee_enabled(void) { return 0; }
