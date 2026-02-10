#!/usr/bin/env python3
"""
Offline parser test script.

Loads debug.html (saved by the scraper) and tests extraction logic
without needing a browser or login. Use this to iterate on selectors.

Usage:
    python test_parser.py
    python test_parser.py --verbose
"""

import os
import re
import argparse
from bs4 import BeautifulSoup
from datetime import datetime

DEBUG_HTML_PATH = os.path.join(os.path.dirname(__file__), "debug.html")


def load_debug_html():
    """Load debug.html and return BeautifulSoup object."""
    if not os.path.exists(DEBUG_HTML_PATH):
        print(f"ERROR: {DEBUG_HTML_PATH} not found!")
        print("Run the scraper first to generate this file.")
        return None

    with open(DEBUG_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Extract metadata from comments
    url_match = re.search(r'<!-- URL: (.+?) -->', html)
    time_match = re.search(r'<!-- TIME: (.+?) -->', html)
    label_match = re.search(r'<!-- DEBUG DUMP: (.+?) -->', html)

    print("=" * 70)
    print("DEBUG HTML LOADED")
    print(f"  File: {DEBUG_HTML_PATH}")
    print(f"  Label: {label_match.group(1) if label_match else 'N/A'}")
    print(f"  URL: {url_match.group(1) if url_match else 'N/A'}")
    print(f"  Time: {time_match.group(1) if time_match else 'N/A'}")
    print(f"  Size: {len(html):,} bytes")
    print("=" * 70)

    return BeautifulSoup(html, "html.parser")


def analyze_page_structure(soup, verbose=False):
    """Analyze the DOM structure of the page."""
    print("\n>>> PAGE STRUCTURE ANALYSIS")
    print("-" * 50)

    # Check for iframes
    iframes = soup.find_all("iframe")
    print(f"Iframes found: {len(iframes)}")
    for i, iframe in enumerate(iframes):
        src = iframe.get("src", "")
        id_ = iframe.get("id", "")
        print(f"  [{i}] id='{id_}' src='{src[:80]}...' " if len(src) > 80 else f"  [{i}] id='{id_}' src='{src}'")

    # Check for shadow DOM hosts (elements with shadow attribute or known shadow hosts)
    print(f"\nShadow DOM indicators:")
    shadow_hosts = soup.find_all(attrs={"shadowroot": True})
    print(f"  Elements with shadowroot attr: {len(shadow_hosts)}")

    # Check for tables
    tables = soup.find_all("table")
    print(f"\nTables found: {len(tables)}")
    for i, table in enumerate(tables[:5]):  # Limit to first 5
        classes = table.get("class", [])
        id_ = table.get("id", "")
        rows = table.find_all("tr")
        print(f"  [{i}] id='{id_}' class={classes} rows={len(rows)}")

    # Check for common assignment container patterns
    print(f"\nCommon container patterns:")
    patterns = [
        ("table tbody tr", soup.select("table tbody tr")),
        (".assignment-row", soup.select(".assignment-row")),
        (".gradebook-item", soup.select(".gradebook-item")),
        ("[class*='assignment']", soup.select("[class*='assignment']")),
        (".item-row", soup.select(".item-row")),
        ("tr[data-*]", soup.find_all("tr", attrs=lambda x: x and any(k.startswith("data-") for k in x.keys()) if x else False)),
    ]
    for name, elements in patterns:
        print(f"  {name}: {len(elements)} elements")


def test_row_selectors(soup, verbose=False):
    """Test various CSS selectors to find assignment rows."""
    print("\n>>> TESTING ROW SELECTORS")
    print("-" * 50)

    selectors = [
        "table tbody tr",
        "table tr",
        ".assignment-row",
        ".gradebook-item",
        ".exam-row",
        ".exam-item",
        "[class*='assignment']",
        "[class*='gradebook']",
        ".list-item",
        ".item-row",
    ]

    best_selector = None
    best_count = 0

    for selector in selectors:
        try:
            elements = soup.select(selector)
            count = len(elements)
            if count > 0:
                print(f"  '{selector}': {count} elements")
                if verbose and count > 0 and count <= 20:
                    for i, el in enumerate(elements[:3]):
                        text = el.get_text(strip=True)[:100]
                        print(f"    [{i}] {text}...")
                if count > best_count:
                    best_count = count
                    best_selector = selector
        except Exception as e:
            print(f"  '{selector}': ERROR - {e}")

    print(f"\n  BEST SELECTOR: '{best_selector}' with {best_count} elements")
    return best_selector


def extract_assignments(soup, selector="table tbody tr", verbose=False):
    """Extract assignments using the given selector."""
    print(f"\n>>> EXTRACTING ASSIGNMENTS (selector: '{selector}')")
    print("-" * 50)

    rows = soup.select(selector)
    print(f"Found {len(rows)} rows to parse\n")

    button_words = {'view', 'submit', 'begin', 'continue', 'open', 'completed',
                   'unavailable', 'closed', 'resubmit', 'view/submit', 'go',
                   'take', 'start', 'resume', 'graded'}

    assignments = []

    for i, row in enumerate(rows):
        if verbose:
            print(f"--- Row {i+1} ---")

        # Get row text
        row_text = row.get_text(strip=True)
        if not row_text:
            if verbose:
                print("  [SKIP] Empty row")
            continue

        # Get cells
        cells = row.find_all("td")

        title = None
        button_text = ""
        due_date = None
        has_score = False
        assignment_url = None

        if verbose:
            print(f"  Raw text: {row_text[:100]}...")
            print(f"  Cells: {len(cells)}")

        if cells:
            for j, cell in enumerate(cells):
                cell_text = cell.get_text(strip=True)
                cell_lower = cell_text.lower()

                if verbose:
                    print(f"    Cell[{j}]: '{cell_text[:60]}...' " if len(cell_text) > 60 else f"    Cell[{j}]: '{cell_text}'")

                if not cell_text:
                    continue

                # Check for unavailable
                if cell_lower == 'unavailable' or cell_lower.startswith('opens'):
                    button_text = cell_text
                    continue

                # Check for button/link
                link = cell.find("a")
                if link:
                    link_text = link.get_text(strip=True).lower()
                    if link_text in button_words or link_text.startswith('opens'):
                        button_text = link.get_text(strip=True)
                        assignment_url = link.get("href")
                        continue

                # Check if cell is button word
                if cell_lower in button_words:
                    button_text = cell_text
                    continue

                # Check for score
                if re.match(r'^\d+(\.\d+)?(/\d+)?%?$', cell_text) or re.match(r'^[A-F][+-]?$', cell_text):
                    has_score = True
                    continue

                # Check for date
                if re.match(r'^\d{1,2}/\d{1,2}', cell_text):
                    due_date = cell_text
                    continue

                month_pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
                if re.search(month_pattern, cell_text, re.IGNORECASE):
                    due_date = cell_text
                    continue

                # Otherwise it's probably the title
                if not title and cell_lower not in button_words:
                    title = cell_text

        else:
            # Non-table row - parse from text
            parts = [p.strip() for p in row_text.split('\n') if p.strip()]
            for part in parts:
                part_lower = part.lower()
                if part_lower in button_words:
                    button_text = part
                elif not title and part_lower not in button_words:
                    if not re.match(r'^\d{1,2}/\d{1,2}', part):
                        title = part

        # Get URL if not found
        if not assignment_url:
            link = row.find("a")
            if link:
                assignment_url = link.get("href")

        # Validate and add
        if title and title.lower() not in button_words and len(title) >= 3:
            assignment = {
                "title": title,
                "button_text": button_text,
                "due_date": due_date,
                "has_score": has_score,
                "url": assignment_url,
            }
            assignments.append(assignment)

            if verbose:
                print(f"  -> EXTRACTED: {assignment}")
        elif verbose:
            print(f"  [SKIP] No valid title")

    print(f"\n>>> EXTRACTION COMPLETE: {len(assignments)} assignments found")
    print("-" * 50)

    for a in assignments:
        status = "submitted" if a["has_score"] else ("unavailable" if "unavailable" in a["button_text"].lower() else "not_started")
        print(f"  - {a['title'][:50]:<50} | {a['button_text']:<15} | {status}")

    return assignments


def dump_raw_html_section(soup, selector, limit=2):
    """Dump raw HTML for a selector to see actual structure."""
    print(f"\n>>> RAW HTML DUMP (selector: '{selector}', limit: {limit})")
    print("-" * 50)

    elements = soup.select(selector)
    for i, el in enumerate(elements[:limit]):
        print(f"\n--- Element {i+1} HTML ---")
        html = str(el)
        # Truncate if too long
        if len(html) > 2000:
            print(html[:2000] + "\n... [truncated]")
        else:
            print(html)


def main():
    parser = argparse.ArgumentParser(description="Test parser on debug.html")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--dump", "-d", type=str, help="Dump raw HTML for a selector")
    parser.add_argument("--selector", "-s", type=str, default="table tbody tr", help="CSS selector to use")
    args = parser.parse_args()

    soup = load_debug_html()
    if not soup:
        return

    # Analyze page structure
    analyze_page_structure(soup, args.verbose)

    # Test row selectors
    best_selector = test_row_selectors(soup, args.verbose)

    # Dump raw HTML if requested
    if args.dump:
        dump_raw_html_section(soup, args.dump)

    # Extract using specified or best selector
    selector = args.selector if args.selector != "table tbody tr" else (best_selector or "table tbody tr")
    extract_assignments(soup, selector, args.verbose)


if __name__ == "__main__":
    main()
