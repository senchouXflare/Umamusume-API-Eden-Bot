"""UI contract test: the Shell 2.0 index.html must keep every DOM id and
static selector that app.js depends on. Run with pytest, no browser needed."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8", errors="replace")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8", errors="replace")

# ids that app.js looks up but creates dynamically itself (never in static HTML)
DYNAMIC_IDS = {"career-pill", "save-races-btn"}

def html_ids():
    return set(re.findall(r'id="([\w-]+)"', INDEX))

def test_all_appjs_ids_exist_in_index_html():
    needed = set(re.findall(r"getElementById\(['\"]([\w-]+)['\"]\)", APP_JS)) - DYNAMIC_IDS
    missing = needed - html_ids()
    assert not missing, f"index.html is missing ids app.js needs: {sorted(missing)}"

def test_static_class_selectors_exist():
    # classes app.js queries that must exist in the static shell (not generated)
    for cls in ("navbar", "split-gutter-controls", "title"):
        assert f'class="{cls}' in INDEX or f' {cls}' in INDEX, f"missing static class: {cls}"
    # .title must contain a <span> (app.js queries '.title span')
    m = re.search(r'class="title"[^>]*>(.*?)</h1>', INDEX, re.S)
    assert m and "<span" in m.group(1), ".title must contain a <span>"

def test_collapse_buttons_present():
    for el_id in ("setup-collapse-btn", "content-collapse-btn"):
        assert f'id="{el_id}"' in INDEX, f"missing {el_id} (app.js collapse logic)"

def test_shell_assets_referenced_and_exist():
    for ref, path in (
        ("/css/shell.css", ROOT / "public" / "css" / "shell.css"),
        ("/js/monitor.js", ROOT / "public" / "js" / "monitor.js"),
        ("/js/nav.js", ROOT / "public" / "js" / "nav.js"),
        ("app.js", ROOT / "public" / "app.js"),
        ("styles.css", ROOT / "public" / "styles.css"),
    ):
        assert ref in INDEX, f"index.html does not reference {ref}"
        assert path.exists(), f"missing asset file: {path}"

def test_shell_v2_body_class():
    assert 'class="shell-v2"' in INDEX, "body must carry shell-v2 class for the new design layer"

def test_parent_filter_asset():
    assert "/js/parent-filter.js" in INDEX, "index.html missing parent-filter.js"
    assert (ROOT / "public" / "js" / "parent-filter.js").exists()
    css = (ROOT / "public" / "css" / "shell.css").read_text(encoding="utf-8", errors="replace")
    assert ".parent-filter-bar" in css and ".pf-chip" in css, "shell.css missing filter styles"

def test_library_tabs():
    assert 'id="lib-tabs"' in INDEX, "library tab bar missing"
    targets = re.findall(r'data-lib-target="([\w-]+)"', INDEX)
    sections = re.findall(r'data-lib="([\w-]+)"', INDEX)
    assert set(targets) == {"decks", "friends", "trainees", "parents", "cards"}, targets
    assert set(targets) == set(sections), "every tab needs a matching lib-section"
    css = (ROOT / "public" / "css" / "shell.css").read_text(encoding="utf-8", errors="replace")
    assert "data-active-lib" in css and ".lib-tab" in css, "shell.css missing tab styles"
