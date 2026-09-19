# -*- coding: utf-8 -*-
"""op 5632 军情响应解析器。

★ 真机抓包 `军情.har` + DEX 逆向 `scriptPages/data/a.java` 方法 B/C/a/b 实证。
★ 四段结构：
  1. 分类统计（category, count）
  2. 分区（3个type，每个含分组名+记录列表）
     - type=1: 成员带状态、有时间偏移和flag
     - type=2: （未见数据）
     - type=3: 成员只ID、有已用时（elapsed）
  3. 额外将领状态列表（genId→status）
  4. 另一批将领状态列表（genId→status）
"""
import struct


def 解析军情(packs):
    """从 op 0xd600 响应包解析军情数据。

    返回 {
      "categories": [{"cat": int, "count": int}],
      "sections": [{
        "type": 1|2|3,
        "groups": [{"name": str, "indices": [int]}],
        "records": [{
          "recordId": int,
          "members": [{"genId": int, "status": int}] 或 [int],
          "targetId": int, "targetType": int, "targetName": str,
          "x": int, "y": int,
          "flagHigh": int, "flagLow": int, "timeOffsetMs": int, "extraLong": int  # type=1
          或 "elapsedTimeRaw": int  # type=3
        }]
      }],
      "extraStatus": [{"genId": int, "status": int}],
      "extraStatus2": [{"genId": int, "status": int}]
    }
    """
    for p in (packs or []):
        if p.get("op") == 0xD600 and p.get("data"):
            b = p["data"]
            if len(b) < 2:
                continue
            o = [0]

            def r(fmt):
                n = struct.calcsize(">" + fmt)
                v = struct.unpack_from(">" + fmt, b, o[0])
                o[0] += n
                return v[0] if len(v) == 1 else v

            def utf():
                n = r("H")
                s = b[o[0]:o[0]+n].decode("utf-8", "replace")
                o[0] += n
                return s

            try:
                # === 第一段：分类统计 ===
                nc = r("h")
                categories = [{"cat": r("b"), "count": r("h")} for _ in range(nc)]

                # === 第二段：分区 ===
                nsec = r("b")
                sections = []
                for _ in range(nsec):
                    sec_type = r("b")
                    sec = {"type": sec_type, "groups": [], "records": []}

                    # 分组
                    ng = r("h")
                    for _ in range(ng):
                        name = utf()
                        ni = r("h")
                        indices = [r("h") for _ in range(ni)]
                        sec["groups"].append({"name": name, "indices": indices})

                    # 记录
                    nr = r("h")
                    for _ in range(nr):
                        rec = {"recordId": r("q")}
                        mc = r("b")
                        if sec_type == 1:
                            rec["members"] = [{"genId": r("q"), "status": r("b")} for _ in range(mc)]
                        else:
                            rec["members"] = [r("q") for _ in range(mc)]

                        rec["targetId"] = r("q")
                        rec["targetType"] = r("b")
                        rec["targetName"] = utf()
                        rec["x"], rec["y"] = r("hh")

                        if sec_type == 1:
                            flag = r("B")
                            rec["flagHigh"] = flag >> 4
                            rec["flagLow"] = flag & 15
                            rec["timeOffsetMs"] = r("i")
                            rec["extraLong"] = r("q")
                        elif sec_type == 3:
                            rec["elapsedTimeRaw"] = r("q")

                        sec["records"].append(rec)

                    sections.append(sec)

                # === 第三段：额外状态 ===
                n3 = r("h")
                extra_status = [{"genId": r("q"), "status": r("b")} for _ in range(n3)]

                # === 第四段：另一批状态 ===
                n4 = r("h")
                extra_status2 = [{"genId": r("q"), "status": r("b")} for _ in range(n4)]

                return {
                    "categories": categories,
                    "sections": sections,
                    "extraStatus": extra_status,
                    "extraStatus2": extra_status2,
                    "consumed": o[0],
                    "total": len(b)
                }
            except Exception:
                continue

    return None
