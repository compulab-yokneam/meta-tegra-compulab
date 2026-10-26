#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run actual Noble ATR/TI mapping functions in a small host-C harness.

Pass --source-tree pointing at a Noble kernel with the layer patches applied.
The supplied source must match the postimages of the real ATR layer patch.
Use --sanitize to enable the host compiler's address/undefined sanitizers.
This tests mapping/error semantics, not kernel locking or physical devices.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    masked = re.sub(
        r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        lambda match: ' ' * len(match.group()), source, flags=re.DOTALL)
    match = re.search(r'\b' + re.escape(name) + r'\s*\(', masked)
    assert match, name
    start = source.rfind('\n\n', 0, match.start()) + 2
    opening = masked.index('{', match.end())
    depth = 0
    for offset in range(opening, len(masked)):
        if masked[offset] == '{':
            depth += 1
        elif masked[offset] == '}':
            depth -= 1
            if depth == 0:
                return source[start:offset + 1] + '\n'
    raise AssertionError('Unterminated function: ' + name)


PRELUDE = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int spinlock_t;
struct mutex { int unused; };
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define spin_lock(p) ((void)(p))
#define spin_unlock(p) ((void)(p))
#define lockdep_assert_held(p) ((void)(p))
#define unlikely(x) (x)
#define GFP_KERNEL 0
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define dev_err(dev, ...) ((void)(dev))
#define dev_dbg(dev, ...) ((void)(dev))
#define dev_warn(dev, ...) ((void)(dev))
#define BIT(n) (1U << (n))
/* ACTUAL_ATR_FLAGS */
static int allocations, fail_allocation;
static void *test_alloc(size_t count, size_t size) {
    if (++allocations == fail_allocation) return NULL;
    return calloc(count, size);
}
#define kzalloc(size, flags) test_alloc(1, size)
#define kmalloc_array(count, size, flags) test_alloc(count, size)
#define kfree(p) free(p)
struct list_head { struct list_head *next, *prev; };
static void init_list(struct list_head *head) { head->next = head->prev = head; }
static void list_add(struct list_head *node, struct list_head *head) {
    node->next = head->next; node->prev = head;
    head->next->prev = node; head->next = node;
}
static void list_del(struct list_head *node) {
    node->next->prev = node->prev; node->prev->next = node->next;
}
static void list_move(struct list_head *node, struct list_head *head) {
    list_del(node); list_add(node, head);
}
#define container_of(p, type, member) ((type *)((char *)(p) - offsetof(type, member)))
#define list_empty(h) ((h)->next == (h))
#define list_for_each_entry(p, h, m) \
    for (struct list_head *cursor = (h)->next; \
         cursor != (h) && ((p) = container_of(cursor, __typeof__(*(p)), m), 1); \
         cursor = cursor->next)
#define list_for_each_entry_reverse(p, h, m) \
    for (struct list_head *cursor = (h)->prev; \
         cursor != (h) && ((p) = container_of(cursor, __typeof__(*(p)), m), 1); \
         cursor = cursor->prev)
static unsigned long find_first_zero_bit(unsigned long *bits, size_t size) {
    size_t i; for (i = 0; i < size; i++) if (!(*bits & (1UL << i))) break;
    return i;
}
static void set_bit(size_t i, unsigned long *bits) { *bits |= 1UL << i; }
static void clear_bit(size_t i, unsigned long *bits) { *bits &= ~(1UL << i); }
struct i2c_atr;
struct i2c_atr_ops {
    int (*attach_addr)(struct i2c_atr *, u32, u16, u16);
    void (*detach_addr)(struct i2c_atr *, u32, u16);
};
struct i2c_atr_alias_pair {
    struct list_head node; bool fixed; u16 addr, alias;
};
struct i2c_atr_alias_pool {
    size_t size; bool shared; spinlock_t lock; u16 *aliases;
    unsigned long *use_mask;
};
struct i2c_atr {
    void *dev, *priv; const struct i2c_atr_ops *ops; u32 flags;
    struct mutex lock; struct i2c_adapter *parent;
};
struct i2c_atr_chan {
    struct i2c_atr *atr; u32 chan_id; struct mutex alias_pairs_lock;
    struct list_head alias_pairs; struct i2c_atr_alias_pool *alias_pool;
    struct mutex orig_addrs_lock; u16 *orig_addrs; unsigned orig_addrs_size;
};
struct i2c_msg { u16 addr; };
struct i2c_adapter { void *algo_data; };
union i2c_smbus_data { u8 byte; };
static struct i2c_adapter upstream;
static int transfer_result, bus_calls;
static u16 bus_addrs[3], smbus_addr, smbus_flags;
static u8 smbus_command;
static int i2c_transfer(struct i2c_adapter *adap, struct i2c_msg *msgs, int num) {
    int i; assert(adap == &upstream); bus_calls++;
    for (i = 0; i < num; i++) bus_addrs[i] = msgs[i].addr;
    return transfer_result;
}
static int i2c_smbus_xfer(struct i2c_adapter *adap, u16 addr,
                         unsigned short flags, char direction, u8 command,
                         int size, union i2c_smbus_data *data) {
    (void)direction; (void)size; (void)data;
    assert(adap == &upstream); bus_calls++; smbus_addr = addr;
    smbus_flags = flags; smbus_command = command; return transfer_result;
}
static int attach_calls, detach_calls, attach_fail_addr = -1;
static int attach(struct i2c_atr *atr, u32 chan, u16 addr, u16 alias) {
    (void)atr; (void)chan; (void)alias; attach_calls++;
    return addr == attach_fail_addr ? -EIO : 0;
}
static void detach(struct i2c_atr *atr, u32 chan, u16 addr) {
    (void)atr; (void)chan; (void)addr; detach_calls++;
}
static const struct i2c_atr_ops test_ops = {attach, detach};
static struct i2c_atr atr;
static struct i2c_atr_chan chan;
static struct i2c_atr_alias_pool pool;
static unsigned long used;
static u16 aliases[] = {0x30, 0x31};
static void initialize(u32 flags) {
    memset(&atr, 0, sizeof(atr)); memset(&chan, 0, sizeof(chan));
    used = 0; allocations = 0; fail_allocation = 0;
    attach_calls = detach_calls = 0; attach_fail_addr = -1;
    bus_calls = transfer_result = 0;
    atr.flags = flags; atr.ops = &test_ops; atr.parent = &upstream; chan.atr = &atr;
    pool.size = ARRAY_SIZE(aliases); pool.aliases = aliases; pool.use_mask = &used;
    chan.alias_pool = &pool; init_list(&chan.alias_pairs);
}
struct device { int unused; };
struct i2c_client { struct device dev; };
/* ACTUAL_TI_DEFINES */
struct ub960_rxport { unsigned nport; u16 aliased_addrs[UB960_MAX_PORT_ALIASES]; };
struct ub960_data { struct i2c_client *client; struct ub960_rxport *rxports[4]; };
static unsigned writes, fail_write;
static u8 last_reg, last_value;
static int ub960_rxport_write(struct ub960_data *priv, u8 chan_id, u8 reg, u8 value) {
    (void)priv; (void)chan_id; last_reg = reg; last_value = value;
    return ++writes == fail_write ? -EIO : 0;
}
static void *i2c_atr_get_driver_data(struct i2c_atr *instance) { return instance->priv; }
'''


TESTS = r'''
static void cleanup(void) {
    struct i2c_atr_alias_pair *entry;
    while (!list_empty(&chan.alias_pairs)) {
        entry = container_of(chan.alias_pairs.next, struct i2c_atr_alias_pair, node);
        i2c_atr_release_alias(&pool, entry->alias);
        i2c_atr_destroy_c2a(&entry);
    }
    free(chan.orig_addrs); assert(!used);
}
static void unpinned(void) {
    struct i2c_atr_alias_pair *entry;
    list_for_each_entry(entry, &chan.alias_pairs, node) assert(!entry->fixed);
}
static void mapping_tests(void) {
    struct i2c_atr_alias_pair *entry;
    struct i2c_msg msgs[3] = {{0x10}, {0x11}, {0x12}};
    struct i2c_adapter adap = {&chan};
    initialize(0);
    assert(!i2c_atr_map_msgs(&chan, msgs, 2));
    assert(msgs[0].addr == 0x30 && msgs[1].addr == 0x31 && used == 3);
    i2c_atr_unmap_msgs(&chan, msgs, 2); unpinned();
    assert(msgs[0].addr == 0x10 && msgs[1].addr == 0x11);
    /* A third address cannot evict either pinned alias in the same transfer. */
    assert(i2c_atr_map_msgs(&chan, msgs, 3) == -ENXIO); unpinned();
    assert(msgs[0].addr == 0x10 && msgs[1].addr == 0x11 && msgs[2].addr == 0x12);
    /* A later transaction must be able to evict a now-unpinned entry. */
    assert(!i2c_atr_map_msgs(&chan, &msgs[2], 1));
    assert(msgs[2].addr == 0x30 || msgs[2].addr == 0x31);
    i2c_atr_unmap_msgs(&chan, &msgs[2], 1); unpinned();
    assert(msgs[2].addr == 0x12 && detach_calls == 1);
    /* A failed replacement releases its alias rather than retaining poison. */
    attach_fail_addr = 0x77;
    assert(!i2c_atr_get_mapping_by_addr(&chan, 0x77));
    assert(used == 1 || used == 2);
    attach_fail_addr = -1;
    entry = i2c_atr_get_mapping_by_addr(&chan, 0x77);
    assert(entry && entry->addr == 0x77 && used == 3);
    cleanup();

    initialize(I2C_ATR_F_STATIC);
    assert(!i2c_atr_get_mapping_by_addr(&chan, 0x10) && !attach_calls);
    assert(!i2c_atr_attach_addr(&adap, 0x10));
    assert(!i2c_atr_attach_addr(&adap, 0x11));
    assert(i2c_atr_attach_addr(&adap, 0x12) == -EBUSY && !detach_calls);
    assert(!i2c_atr_get_mapping_by_addr(&chan, 0x12));
    i2c_atr_detach_addr(&adap, 0x10); assert(used == 2);
    assert(!i2c_atr_attach_addr(&adap, 0x12));
    assert(used == 3); cleanup();

    initialize(I2C_ATR_F_STATIC | I2C_ATR_F_PASSTHROUGH);
    msgs[0].addr = 0x77;
    assert(!i2c_atr_map_msgs(&chan, msgs, 1) && msgs[0].addr == 0x77);
    i2c_atr_unmap_msgs(&chan, msgs, 1);
    assert(!attach_calls && !used); cleanup();

    initialize(0); fail_allocation = 1;
    assert(!i2c_atr_create_mapping_by_addr(&chan, 0x10));
    assert(!used && list_empty(&chan.alias_pairs) && !attach_calls); cleanup();
    initialize(0); attach_fail_addr = 0x10;
    assert(!i2c_atr_create_mapping_by_addr(&chan, 0x10));
    assert(!used && list_empty(&chan.alias_pairs)); cleanup();
    initialize(0);
    assert(i2c_atr_get_mapping_by_addr(&chan, 0x10));
    fail_allocation = allocations + 1;
    assert(i2c_atr_get_mapping_by_addr(&chan, 0x11));
    assert(used == 1 && detach_calls == 1); cleanup();
    initialize(I2C_ATR_F_STATIC); attach_fail_addr = 0x10;
    assert(i2c_atr_attach_addr(&adap, 0x10) == -EBUSY);
    assert(!used && list_empty(&chan.alias_pairs)); cleanup();
    initialize(0); fail_allocation = 1;
    assert(i2c_atr_map_msgs(&chan, msgs, 1) == -ENOMEM);
    assert(msgs[0].addr == 0x77 && !used && !attach_calls); cleanup();
    puts("PASS: actual ATR functions: dynamic/static/passthrough, pinning, unwind, allocations");
}
static void transfer_tests(void) {
    struct i2c_adapter adap = {&chan};
    struct i2c_msg msgs[] = {{0x10}, {0x11}};
    union i2c_smbus_data data = {0};
    initialize(0); transfer_result = -EIO;
    assert(i2c_atr_master_xfer(&adap, msgs, 2) == -EIO);
    assert(bus_calls == 1 && bus_addrs[0] == 0x30 && bus_addrs[1] == 0x31);
    assert(msgs[0].addr == 0x10 && msgs[1].addr == 0x11); unpinned();
    transfer_result = 2;
    assert(i2c_atr_master_xfer(&adap, msgs, 2) == 2);
    assert(msgs[0].addr == 0x10 && msgs[1].addr == 0x11); unpinned(); cleanup();

    initialize(I2C_ATR_F_STATIC);
    assert(i2c_atr_master_xfer(&adap, msgs, 2) == -ENXIO);
    assert(!bus_calls && msgs[0].addr == 0x10 && msgs[1].addr == 0x11);
    assert(i2c_atr_smbus_xfer(&adap, 0x10, 0, 0, 0x44, 1, &data) == -ENXIO);
    assert(!bus_calls); cleanup();

    initialize(0); transfer_result = -EIO;
    assert(i2c_atr_smbus_xfer(&adap, 0x10, 3, 1, 0x44, 1, &data) == -EIO);
    assert(smbus_addr == 0x30 && smbus_flags == 3 && smbus_command == 0x44);
    assert(used == 1 && bus_calls == 1); cleanup();

    initialize(I2C_ATR_F_STATIC | I2C_ATR_F_PASSTHROUGH);
    assert(!i2c_atr_smbus_xfer(&adap, 0x77, 0, 0, 0x55, 1, &data));
    assert(smbus_addr == 0x77 && !used && !attach_calls); cleanup();
    puts("PASS: actual I2C/SMBus functions: alias translation, backend errors and original addresses");
}
static void ti_tests(void) {
    struct i2c_client client = {0};
    struct ub960_rxport port = {0};
    struct ub960_data priv = {.client = &client, .rxports = {&port}};
    struct i2c_atr instance = {.priv = &priv};
    unsigned i;
    writes = fail_write = 0;
    for (i = 0; i < UB960_MAX_PORT_ALIASES; i++) {
        assert(!ub960_atr_attach_addr(&instance, 0, i, 0x30 + i));
        assert(port.aliased_addrs[i] == i + 1);
    }
    assert(ub960_atr_attach_addr(&instance, 0, 0x55, 0x66) == -EADDRNOTAVAIL);
    assert(writes == 2 * UB960_MAX_PORT_ALIASES);
    ub960_atr_detach_addr(&instance, 0, 0);
    assert(!port.aliased_addrs[0] && !last_value);
    assert(!ub960_atr_attach_addr(&instance, 0, 0x55, 0x66));
    assert(port.aliased_addrs[0] == 0x56);
    memset(&port, 0, sizeof(port));
    writes = 0; fail_write = 1;
    assert(ub960_atr_attach_addr(&instance, 0, 0x10, 0x30) == -EIO);
    assert(!port.aliased_addrs[0]);
    writes = 0; fail_write = 2;
    assert(ub960_atr_attach_addr(&instance, 0, 0x10, 0x30) == -EIO);
    assert(!port.aliased_addrs[0] && writes == 3);
    assert(last_reg == UB960_RR_SLAVE_ALIAS(0) && !last_value);
    writes = fail_write = 0;
    assert(!ub960_atr_attach_addr(&instance, 0, 0x10, 0x30));
    assert(port.aliased_addrs[0] == 0x11);
    ub960_atr_detach_addr(&instance, 0, 0x10);
    assert(!port.aliased_addrs[0]);
    i = writes; ub960_atr_detach_addr(&instance, 0, 0x77); assert(writes == i);
    puts("PASS: actual TI callbacks: every slot, address zero, exhaustion and I2C write failures");
}
int main(void) { mapping_tests(); transfer_tests(); ti_tests(); return 0; }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path, required=True)
    parser.add_argument('--patch', type=Path, default=(
        Path(__file__).resolve().parents[1] /
        'files/adi-gmsl-v18-noble/'
        '0001-i2c-atr-backport-address-mapping-for-noble.patch'))
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    patch = args.patch.read_text()
    files = {}
    for block in patch.split('diff --git ')[1:]:
        name = re.search(r'^a/(.*?) b/', block).group(1)
        expected = re.search(r'^index [a-f0-9]+\.\.([a-f0-9]+)', block, re.MULTILINE).group(1)
        content = (args.source_tree / name).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        assert blob.startswith(expected), 'Source differs from patch postimage: ' + name
        files[name] = content.decode()
    core = files['drivers/i2c/i2c-atr.c']
    ti = files['drivers/media/i2c/ds90ub960.c']
    flags = re.search(r'enum i2c_atr_flags \{.*?\};',
                      files['include/linux/i2c-atr.h'], re.DOTALL).group(0)
    defines = '\n'.join(re.search(r'^#define ' + name + r'[^\n]*', ti,
                                  re.MULTILINE).group(0)
                        for name in ('UB960_MAX_PORT_ALIASES',
                                     'UB960_RR_SLAVE_ID', 'UB960_RR_SLAVE_ALIAS'))
    prelude = PRELUDE.replace('/* ACTUAL_ATR_FLAGS */', flags)
    prelude = prelude.replace('/* ACTUAL_TI_DEFINES */', defines)
    assert 'I2C_ATR_F_STATIC' in function(ti, 'ub960_init_atr')
    for model in ('913', '953'):
        adapter = function(files['drivers/media/i2c/ds90ub' + model + '.c'],
                           'ub' + model + '_add_i2c_adapter')
        assert 'struct i2c_atr_adap_desc desc' in adapter
        assert 'i2c_atr_add_adapter(priv->plat_data->atr, &desc)' in adapter
    names = (
        'i2c_atr_create_c2a', 'i2c_atr_destroy_c2a', 'i2c_atr_reserve_alias',
        'i2c_atr_release_alias', 'i2c_atr_find_mapping_by_addr',
        'i2c_atr_create_mapping_by_addr', 'i2c_atr_replace_mapping_by_addr',
        'i2c_atr_get_mapping_by_addr', 'i2c_atr_map_msgs', 'i2c_atr_unmap_msgs',
        'i2c_atr_master_xfer', 'i2c_atr_smbus_xfer',
        'i2c_atr_attach_addr', 'i2c_atr_detach_addr',
    )
    extracted = ''.join(function(core, name) for name in names)
    extracted += function(ti, 'ub960_atr_attach_addr')
    extracted += function(ti, 'ub960_atr_detach_addr')
    with tempfile.TemporaryDirectory(prefix='noble-atr-c-test.') as directory:
        source = Path(directory) / 'test.c'
        binary = Path(directory) / 'test'
        source.write_text(prelude + extracted + TESTS)
        command = ['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                   '-Wno-sign-compare', '-O2', '-o', str(binary), str(source)]
        if args.sanitize:
            command += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        subprocess.run(command, check=True)
        subprocess.run([str(binary)], check=True)
    print('PASS: all five source files match the actual patch postimages')


if __name__ == '__main__':
    main()
