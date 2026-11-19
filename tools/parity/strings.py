# IDA batch: strings -> referencing functions (dump/strings.txt), without touching funcs.txt
import idautils, idc, ida_auto, os
ida_auto.auto_wait()
out = os.path.join(os.path.dirname(idc.get_idb_path()), "dump", "strings.txt")
with open(out, "w", encoding="utf-8") as f:
    for s in idautils.Strings():
        refs = sorted({idc.demangle_name(idc.get_func_name(x.frm), idc.get_inf_attr(idc.INF_SHORT_DN)) or idc.get_func_name(x.frm) or ("%X" % x.frm) for x in idautils.XrefsTo(s.ea)})
        try: txt = str(s)
        except Exception: continue
        f.write("%X\t%s\t%s\n" % (s.ea, txt.replace("\n", "\n").replace("\t", "\t"), " | ".join(refs[:8])))
idc.qexit(0)
