import re
import sys
from pathlib import Path
from dotenv import dotenv_values

n = sys.argv[1]
p = Path("/Users/shadowwolf/premanand-poc/.env")
new_key = dotenv_values(p)["GEMINI_API_KEY_" + n]

out = []
replaced = 0
for line in p.read_text().splitlines():
    if re.match(r"\s*(export\s+)?GEMINI_API_KEY\s*=", line):
        out.append("GEMINI_API_KEY=" + new_key)
        replaced += 1
    else:
        out.append(line)
p.write_text("\n".join(out) + "\n")

after = dotenv_values(p)
print("lines replaced:", replaced, "| GEMINI_API_KEY now ..." + after["GEMINI_API_KEY"][-4:])
