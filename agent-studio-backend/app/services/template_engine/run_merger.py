"""Merge split XML runs in python-pptx paragraphs.

PowerPoint often splits a single placeholder like ``{{ client_name }}`` across
multiple ``<a:r>`` (run) elements.  This module provides helpers to work at
the *paragraph* level so placeholders that span runs are handled correctly.

It also handles the cross-paragraph case: when a placeholder description
contains line-breaks, PowerPoint stores the opening ``{{`` and closing ``}}``
in separate ``<a:p>`` elements.  ``merge_multiline_placeholders`` collapses
these back into a single paragraph before regex matching.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def _save_font(run) -> Dict:
    """Snapshot run-level formatting so it can be restored after edits."""
    font = run.font
    cfg: Dict = {
        "name": font.name,
        "size": font.size,
        "bold": font.bold,
        "italic": font.italic,
        "underline": font.underline,
    }
    return cfg


def _restore_font(cfg: Dict, run) -> None:
    """Re-apply a previously saved font configuration."""
    font = run.font
    if cfg.get("name"):
        font.name = cfg["name"]
    if cfg.get("size"):
        font.size = cfg["size"]
    if cfg.get("bold") is not None:
        font.bold = cfg["bold"]
    if cfg.get("italic") is not None:
        font.italic = cfg["italic"]
    if cfg.get("underline") is not None:
        font.underline = cfg["underline"]


def paragraph_text(paragraph) -> str:
    """Full text of a paragraph, concatenated across all runs."""
    return "".join(run.text for run in paragraph.runs)


def replace_in_paragraph(paragraph, old: str, new: str) -> bool:
    """Replace *old* with *new* across potentially split runs.

    Returns ``True`` if a replacement was made.  Preserves the formatting
    of the first run that participates in the match.
    """
    runs = list(paragraph.runs)
    if not runs:
        return False

    full = "".join(r.text for r in runs)
    idx = full.find(old)
    if idx == -1:
        return False

    run_boundaries: List[Tuple[int, int]] = []
    pos = 0
    for r in runs:
        end = pos + len(r.text)
        run_boundaries.append((pos, end))
        pos = end

    match_start = idx
    match_end = idx + len(old)

    first_run_idx = None
    for i, (rs, re_) in enumerate(run_boundaries):
        if rs <= match_start < re_:
            first_run_idx = i
            break

    last_run_idx = None
    for i, (rs, re_) in enumerate(run_boundaries):
        if rs < match_end <= re_:
            last_run_idx = i
            break

    if first_run_idx is None or last_run_idx is None:
        return False

    if first_run_idx == last_run_idx:
        r = runs[first_run_idx]
        saved = _save_font(r)
        local_start = match_start - run_boundaries[first_run_idx][0]
        local_end = match_end - run_boundaries[first_run_idx][0]
        r.text = r.text[:local_start] + new + r.text[local_end:]
        _restore_font(saved, r)
    else:
        first_r = runs[first_run_idx]
        local_start = match_start - run_boundaries[first_run_idx][0]
        saved = _save_font(first_r)
        first_r.text = first_r.text[:local_start] + new
        _restore_font(saved, first_r)

        for mid_idx in range(first_run_idx + 1, last_run_idx):
            runs[mid_idx].text = ""

        last_r = runs[last_run_idx]
        local_end = match_end - run_boundaries[last_run_idx][0]
        last_r.text = last_r.text[local_end:]

    return True


def replace_all_in_paragraph(paragraph, old: str, new: str) -> int:
    """Replace every occurrence of *old* in the paragraph. Returns count."""
    count = 0
    while replace_in_paragraph(paragraph, old, new):
        count += 1
    return count


def merge_multiline_placeholders(text_frame) -> int:
    """Collapse placeholders that span multiple paragraphs into one.

    PowerPoint stores line-breaks inside a text box as separate ``<a:p>``
    elements.  When a placeholder description contains line-breaks the
    opening ``{{`` and closing ``}}`` end up in different paragraphs and
    per-paragraph regex matching fails silently.

    This helper scans the paragraphs of *text_frame*, detects any ``{{``
    that is not closed on the same paragraph, absorbs the continuation
    paragraphs' text into the opening paragraph's last run, and removes
    the now-empty continuation ``<a:p>`` elements from the XML tree.

    Returns the number of merges performed (0 when nothing was needed).
    """
    paras = list(text_frame.paragraphs)
    if len(paras) < 2:
        return 0

    txBody = paras[0]._p.getparent()
    merges = 0
    i = 0

    while i < len(paras):
        p_text = paragraph_text(paras[i])
        open_count = p_text.count("{{")
        close_count = p_text.count("}}")

        if open_count > close_count:
            j = i + 1
            merged_text = p_text
            while j < len(paras):
                cont_text = paragraph_text(paras[j])
                merged_text += " " + cont_text
                if merged_text.count("}}") >= merged_text.count("{{"):
                    break
                j += 1

            if j >= len(paras):
                i += 1
                continue

            anchor_para = paras[i]
            runs = list(anchor_para.runs)
            if runs:
                last_run = runs[-1]
                for k in range(i + 1, j + 1):
                    last_run.text += " " + paragraph_text(paras[k])
            else:
                anchor_para.text = merged_text

            for k in range(i + 1, j + 1):
                txBody.remove(paras[k]._p)

            merges += 1
            logger.debug(
                "Merged %d continuation paragraphs into paragraph %d",
                j - i, i,
            )
            paras = list(text_frame.paragraphs)
        else:
            i += 1

    return merges
