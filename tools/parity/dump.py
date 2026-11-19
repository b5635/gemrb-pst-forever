# IDA batch: wait for analysis, dump functions, strings + referencing functions
import idaapi, idautils, idc, ida_auto, ida_funcs, json, os
ida_auto.auto_wait()
out = os.path.join(os.path.dirname(idc.get_idb_path()), "dump")
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "funcs.txt"), "w") as f:
    for ea in idautils.Functions():
        f.write("%08X %s %d\n" % (ea, idc.get_func_name(ea), ida_funcs.get_func(ea).size()))
with open(os.path.join(out, "strings.txt"), "w", encoding="utf-8") as f:
    for s in idautils.Strings():
        refs = sorted({idc.get_func_name(x.frm) or ("%08X" % x.frm) for x in idautils.XrefsTo(s.ea)})
        try: txt = str(s)
        except Exception: continue
        f.write("%08X\t%s\t%s\n" % (s.ea, txt.replace("\n","\n").replace("\t","\t"), ",".join(refs[:8])))
idc.qexit(0)
