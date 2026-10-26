#!/bin/sh

. /usr/bin/uefi_common.func

rc=0
value="\004\000\000\000\000\000\000\000"
set_efi_var "OsIndications" "8be4df61-93ca-11d2-aa0d-00e098032b8c" "$value" || rc=1
exit $rc
