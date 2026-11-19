import idc, ida_auto, ida_bytes, os, ida_ida
ida_auto.auto_wait()
base = os.path.dirname(idc.get_idb_path())
ptr = 8 if ida_ida.inf_is_64bit() else 4
rd = ida_bytes.get_qword if ptr == 8 else ida_bytes.get_dword
with open(os.path.join(base, "dump", "vt.txt"), "w") as f:
    for l in open(os.path.join(base, "vt_ea.txt")).read().split():
        ea = int(l, 16)
        for i in range(int(os.environ.get("VT_SLOTS", "24"))):
            if i and not idc.get_func_name(rd(ea + i*ptr)): break
            fn = rd(ea + i*ptr)
            n = idc.get_func_name(fn)
            f.write("%X\t%d\t%X\t%s\n" % (ea, i, fn, idc.demangle_name(n, idc.get_inf_attr(idc.INF_SHORT_DN)) or n))
idc.qexit(0)
