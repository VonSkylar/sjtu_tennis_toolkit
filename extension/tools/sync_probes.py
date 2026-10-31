"""Development-only: port the existing page probes as packaged, executable JS.

The extension never executes Python, eval, or downloaded source at runtime.
"""
from pathlib import Path
import ast
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sjtu_tennis_toolkit.browser.js_snippets import GRID_HELPERS, grid_probe
from sjtu_tennis_toolkit.constants import BOOKING_GRID_GEOMETRY

SPECS = {
    "cell": ("booking_actions", "_slot_cell_state"),
    "scroll": ("booking_actions", "_scroll_slot_into_view"),
    "notice": ("booking_actions", "_notice_text"),
    "scan": ("monitor", "_extract_available_slots"),
    "dates": ("rusher", "_date_tab_state"),
    "grid": ("rusher", "_target_grid_state"),
}

def generate():
    result = ["// Ported from the existing Python browser probes; see tools/sync_probes.py.\n",
              "globalThis.SJTU_PROBES = (() => {\n",
              "const geom = " + json.dumps(BOOKING_GRID_GEOMETRY) + ";\n", GRID_HELPERS, "\nreturn {geometry: geom,\n"]
    for name, (module, method) in SPECS.items():
        tree = ast.parse((ROOT / "sjtu_tennis_toolkit" / "browser" / f"{module}.py").read_text(encoding="utf-8"))
        func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
        call = next(n for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "grid_probe")
        expression = grid_probe(*(ast.literal_eval(a) for a in call.args)).replace(GRID_HELPERS, "")
        if module == "rusher":
            expression = expression.replace(r"\\d", r"\d")
        if name == "cell":
            # 'unavailable' contains 'available'; a disabled class must win.
            marker = "const hasGreen = colors.some"
            expression = expression.replace(marker, "if (/不可选|已约|已满|禁用|disabled|disable|unavailable|booked|sold|reserved/i.test(combined)) return {state:'unavailable',reason:'格子标记为不可选'};\n                " + marker)
        result.append(f"{name}: {expression},\n")
    result.append("};\n})();\n")
    return "".join(result)

if __name__ == "__main__":
    (ROOT / "extension" / "probes.js").write_text(generate(), encoding="utf-8")
