"""Applies a parsing spec to a CSQ entry, in place of a hand-written `_parse_*`.

This is the generic half of the planned annotation-API work: the spec says what
to read and how to shape it, this module does it. Output is a plain dict (the
generic annotation payload), not a per-plugin pydantic model.

Currently additive — the hand-written parsers in vcf_results are still the ones
wired into the response. This runs alongside them so the two can be compared
over the same CSQ fixtures (see tests/test_spec_interpreter.py).
"""

import json
import re
from urllib.parse import unquote
from functools import lru_cache
from pathlib import Path

from vep.models.parsing_spec_model import PluginSpec, TargetSpec, WhenSpec
from vep.utils.csq import (
    first_amp,
    get_csq_value,
    has_any_column,
    raw_amp,
    split_amp,
    to_float,
)

# Some plugins write a literal 'NA' for "no value here".
_NULLISH = ("", "NA")

_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")


def _is_present(value) -> bool:
    """Whether a built output actually carries something.

    Deliberately not plain truthiness: an allele frequency of 0.0 is a real
    value, and `not 0.0` would throw it away.
    """
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)):
        return len(value) > 0
    return True


def _coerce(raw: str | None, value_type: str, field_spec=None):
    """A raw CSQ value as `value_type`, or None if absent/'NA'/unparseable."""
    if raw is None or raw in _NULLISH:
        return None
    if field_spec is not None and raw in (field_spec.null_values or ()):
        return None
    if value_type == "float":
        return to_float(raw)
    if value_type == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if field_spec is not None:
        for find, replacement in (field_spec.replace or {}).items():
            raw = raw.replace(find, replacement)
        if field_spec.strip:
            raw = raw.strip()
    return raw


def _column(csq_values: list[str], name: str, index_map: dict[str, int]) -> str | None:
    return get_csq_value(csq_values, name, None, index_map)


def _should_drop(row: dict, drop_when, csq_values=None, index_map=None) -> bool:
    if drop_when is None:
        return False
    # A conditional rule only applies to elements it names (the allele rule is
    # for a "Variation" phenotype, not a "Gene" one).
    condition = drop_when.only_if
    if condition is not None and row.get(condition.field) != condition.equals:
        return False
    if drop_when.all_null:
        return all(value is None for value in row.values())
    if drop_when.unless_matches is not None:
        match = drop_when.unless_matches
        # None (an absent field, or a column this output doesn't carry) never
        # matches, so the element drops.
        column_value = (
            _column(csq_values, match.column, index_map)
            if csq_values is not None and index_map is not None
            else None
        )
        return row.get(match.field) != column_value or column_value in (None, "")
    return row.get(drop_when.null) is None


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@lru_cache(maxsize=None)
def _lookup_table(name: str) -> dict[str, str]:
    """A shipped reference table, as value -> label. Two on-disk shapes, because
    which is smaller depends on how many distinct labels there are.

    *Grouped* (`{label: [members]}`) suits a handful of labels over many members
    — GO's 38k ids across three aspects — and is inverted once here. Members are
    compared as strings so a table may store them as numbers: GO ids lose their
    `GO:` prefix and become ints on disk, which is most of the saving.

    *Flat* (`{"terms": {member: label}}`) suits near-unique labels, where
    grouping would store 62k single-member lists and cost more than it saves —
    EFO's ontology term names. Sibling keys (`version`, `retired`) are metadata
    about the table, not entries in it.
    """
    path = DATA_DIR / f"{name}.json"
    document = json.loads(path.read_text())
    if "terms" in document:
        return {str(key): label for key, label in document["terms"].items()}
    return {
        str(member): label for label, members in document.items() for member in members
    }


def _lookup_key(value) -> str | None:
    """The table key for a parsed value.

    GO ids arrive as `GO:0000122` and the aspect table stores `122` — the prefix
    is on every id there and carries nothing. An accession with no colon
    (`EFO_0006336`, from OpenTargets) is already the key: its prefix *is*
    meaningful, since one table spans several ontologies.
    """
    if not isinstance(value, str):
        return None
    head, sep, tail = value.partition(":")
    if not sep:
        return head or None
    if not tail:
        return None
    return str(int(tail)) if tail.isdigit() else tail


def _resolve_curie(value, prefer, templates, sep):
    """One URL from a CURIE list, choosing which authority to trust.

    A source that names a thing in several ontologies at once has no single id.
    `prefer` is the order to try; anything with a known template is taken as a
    last resort, so a list of only unpreferred sources still links. Returns
    (url, curie), both None when nothing is usable.
    """
    if not value:
        return None, None
    # Decode *first*, which is the exception to the split-before-decode rule the
    # rest of this module follows — and the reason is in the source: ClinVar
    # escapes the comma that separates one CURIE from the next, so the separator
    # only exists after decoding. Splitting the raw value finds one CURIE where
    # there are several, and the wrong authority wins the `prefer` order.
    #
    # The cost is that this post-op's own output is decoded a second time by the
    # final pass. Harmless for the numeric accessions ClinVar publishes; wrong
    # for any label carrying a literal '%'.
    curies = [part.strip() for part in unquote(str(value)).split(sep) if part.strip()]
    by_prefix: dict[str, str] = {}
    for curie in curies:
        prefix, _, accession = curie.partition(":")
        # MONDO writes itself as `MONDO:MONDO:0060578` — the tag plus a
        # self-prefixing CURIE — so an accession keeping its own prefix is
        # normal, not a duplication bug.
        if accession and prefix not in by_prefix:
            by_prefix[prefix] = accession
    order = list(prefer or []) + [p for p in by_prefix if p not in (prefer or [])]
    for prefix in order:
        accession = by_prefix.get(prefix)
        template = (templates or {}).get(prefix)
        if accession and template:
            bare = accession.split(":")[-1]
            return template.replace("{id}", bare), f"{prefix}:{accession}"
    return None, None


def _apply_post(rows: list[dict], post) -> list[dict]:
    """Whole-list operations, in the order the spec lists them."""
    for operation in post or []:
        if operation.op == "lookup":
            table = _lookup_table(operation.table)
            for row in rows:
                key = _lookup_key(row.get(operation.by))
                row[operation.into] = table.get(key) if key else None
            continue
        if operation.op == "concat":
            for row in rows:
                parts = [row.get(field) for field in operation.fields or []]
                # A missing part makes the whole value absent: OpenTargets
                # publishes a beta with no p-value for some associations, and
                # "e-28" or "3.32e" would be worse than nothing.
                row[operation.into] = (
                    None
                    if any(part is None or part == "" for part in parts)
                    else operation.sep.join(str(part) for part in parts)
                )
            continue
        if operation.op == "curie_link":
            for row in rows:
                url, label = _resolve_curie(
                    row.get(operation.by), operation.prefer, operation.templates,
                    operation.curie_sep,
                )
                row[operation.into] = url
                if operation.label_into:
                    row[operation.label_into] = label
            continue
        if operation.op == "dedup":
            # Keyed on the row's JSON rather than a tuple of its values: after a
            # join a row can hold a list, and a tuple containing one is
            # unhashable — which raised at request time for any `dedup` in
            # `post_joins`.
            seen = set()
            unique = []
            for row in rows:
                key = json.dumps(row, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            rows = unique
        elif operation.op == "exclude":
            unwanted = {value.casefold() for value in operation.values or []}
            rows = [
                row
                for row in rows
                if not (
                    isinstance(row.get(operation.by), str)
                    and row[operation.by].casefold() in unwanted
                )
            ]
        elif operation.op == "sort":
            # Partitioned rather than sorted against a sentinel value. A sentinel
            # has to be comparable with the real keys, so a string column with
            # one null raised TypeError, and a row missing the field entirely
            # raised KeyError — both at request time, on data the spec had no
            # way to forbid. Partitioning also delivers what the docstring
            # promises: `nulls` places them independently of `desc`.
            keyed = [row for row in rows if row.get(operation.by) is not None]
            absent = [row for row in rows if row.get(operation.by) is None]
            keyed.sort(key=lambda row: row[operation.by], reverse=operation.desc)
            rows = keyed + absent if operation.nulls == "last" else absent + keyed
    return rows


def _aligned_rows(columns, field_specs, align, const=None):
    """N positionally aligned columns -> one row per position.

    `align` says what to do with columns of different length: `max` keeps every
    position and leaves the short columns null there, anything else stops at the
    shortest. `const` tags each row with values the columns do not carry.
    """
    lengths = [len(column) for column in columns]
    length = (max(lengths) if align == "max" else min(lengths)) if lengths else 0
    for i in range(length):
        row = {
            field_spec.field: _coerce(
                column[i] if i < len(column) else None, field_spec.type, field_spec
            )
            for column, field_spec in zip(columns, field_specs)
        }
        if const:
            row.update(const)
        yield row


def _apply_zip(csq_values, index_map, target: TargetSpec) -> list[dict]:
    """N positionally-aligned '&'-lists -> a list of objects.

    Uses the position-preserving split: an 'NA' still occupies a slot, which is
    what keeps the columns aligned with each other.
    """
    columns = [
        raw_amp(_column(csq_values, name, index_map), target.sep)
        for name in target.source
    ]
    rows = [
        row
        for row in _aligned_rows(columns, target.as_fields, target.align)
        if not _should_drop(row, target.drop_when, csq_values, index_map)
    ]
    return _apply_post(rows, target.post)


def _apply_stack(csq_values, index_map, target: TargetSpec) -> list[dict]:
    """Several groups of columns -> one list, each group's rows tagged.

    Each group is a `zip` over its own columns -- literally the same alignment,
    plus the group's `const` -- so a group of scalar columns yields a single row
    and a group of list columns yields one row per position. `drop_when` and
    `post` then apply to the whole stack, which is what lets one `curie_link`
    resolve every group's ids.
    """
    rows: list[dict] = []
    for group in target.of:
        columns = [
            raw_amp(_column(csq_values, name, index_map), group.sep)
            if group.split
            else ([raw] if (raw := _column(csq_values, name, index_map)) else [])
            for name in group.source
        ]
        rows += [
            row
            for row in _aligned_rows(
                columns, group.as_fields, group.align, group.const
            )
            if not _should_drop(row, target.drop_when, csq_values, index_map)
        ]
    return _apply_post(rows, target.post)


def _apply_regex(csq_values, index_map, target: TargetSpec):
    """Named regex groups -> object(s). Non-matching items are skipped."""
    raw = _column(csq_values, target.source, index_map)
    compiled = re.compile(target.pattern)
    items = split_amp(raw, target.sep) if target.each else ([raw] if raw else [])

    rows = []
    for item in items:
        match = compiled.match(item)
        if not match:
            continue
        row = {
            field_spec.field: _coerce(
                match.group(field_spec.field), field_spec.type, field_spec
            )
            for field_spec in target.as_fields
        }
        if _should_drop(row, target.drop_when, csq_values, index_map):
            continue
        rows.append(row)
    # Whole-list ops only mean something for the per-item form; `each: false`
    # produces one object, not a list.
    if target.each:
        return _apply_post(rows, target.post)
    return rows[0] if rows else None


def pattern_affixes(from_pattern: str) -> tuple[str, str]:
    """The literal (prefix, suffix) around the `{placeholder}` of a `pattern_map`
    `from_pattern`: a column matches iff it is `prefix + <key> + suffix`, so a
    matched key maps back to its column as `f"{prefix}{key}{suffix}"`."""
    placeholder = _PLACEHOLDER_RE.search(from_pattern)
    return from_pattern[: placeholder.start()], from_pattern[placeholder.end() :]


def _apply_pattern_map(csq_values, index_map, target: TargetSpec) -> dict:
    """Columns matching `from_pattern` -> {wildcard: value}.

    The columns are discovered from the CSQ header, so whichever ancestries a
    run actually emitted come through without being named in the spec.
    """
    prefix, suffix = pattern_affixes(target.from_pattern)
    excluded = set(target.exclude or [])

    values: dict = {}
    for column in index_map:
        if column in excluded:
            continue
        if not (column.startswith(prefix) and column.endswith(suffix)):
            continue
        key = column[len(prefix) : len(column) - len(suffix)]
        value = _coerce(_column(csq_values, column, index_map), target.type)
        if value is not None:
            values[key] = value
    return values


def _build_object(tokens: list[str], field_specs, source_text: str) -> dict:
    """Assign `tokens` to `field_specs` strictly by index.

    A `raw`-typed field takes `source_text` and consumes no slot. Slots past the
    end of `tokens` are null: a missing item leaves *its own* field empty and
    does not shift its neighbours along.
    """
    built: dict = {}
    position = 0
    for field_spec in field_specs:
        if field_spec.type == "raw":
            built[field_spec.field] = source_text
            continue
        token = tokens[position] if position < len(tokens) else None
        built[field_spec.field] = _coerce(token, field_spec.type, field_spec)
        position += 1
    return built


def _apply_chunk(csq_values, index_map, target: TargetSpec) -> list[dict]:
    """Fixed-size groups of '&'-items -> a list of objects."""
    raw = _column(csq_values, target.source, index_map)
    tokens = raw.split(target.sep) if raw else []

    rows = []
    for start in range(0, len(tokens), target.size):
        group = tokens[start : start + target.size]
        row = _build_object(
            group, target.as_fields, target.sep.join(t for t in group if t)
        )
        if _should_drop(row, target.drop_when, csq_values, index_map):
            continue
        rows.append(row)
    return _apply_post(rows, target.post)


def _apply_positional(csq_values, index_map, target: TargetSpec):
    """'&'-items -> one object, assigned by index."""
    raw = _column(csq_values, target.source, index_map)
    if not raw:
        return [] if target.wrap == "list" else None
    built = _build_object(raw.split(target.sep), target.as_fields, raw)
    return [built] if target.wrap == "list" else built


def _apply_records(csq_values, index_map, target: TargetSpec) -> list[dict]:
    """Two levels of separator: records, then each record's fields by index.

    A source that packs whole sub-records into one column needs both — ClinVar
    writes 15 fields per submitter and 5 per RCV, with '~' inside a record and
    ',' (which VEP rewrites to '&') between them.
    """
    raw = _column(csq_values, target.source, index_map)
    rows: list[dict] = []
    for record in split_amp(raw, target.sep):
        row = _build_object(record.split(target.item_sep), target.as_fields, record)
        if _should_drop(row, target.drop_when, csq_values, index_map):
            continue
        rows.append(row)
    return _apply_post(rows, target.post)


def _apply_key_value(csq_values, index_map, target: TargetSpec) -> dict:
    """A ':'-delimited 'k=v' string -> {k: v}.

    Order-independent by construction, unlike a plain scalar copy of the same
    string. A piece without `kv_delimiter` is dropped rather than raising: a
    malformed piece should not break parsing of an otherwise-good value.
    """
    raw = _column(csq_values, target.source, index_map)
    if not raw:
        return {}
    values: dict = {}
    for piece in raw.split(target.pair_delimiter):
        if target.kv_delimiter not in piece:
            continue
        key, value = piece.split(target.kv_delimiter, 1)
        values[key] = value
    return values


def _when_holds(csq_values, index_map, when: WhenSpec | None) -> bool:
    if when is None:
        return True
    return when.includes in split_amp(_column(csq_values, when.field, index_map))


def _empty_value(target: TargetSpec):
    """What a target yields when its `when` condition does not hold."""
    if target.transform in ("list", "zip", "chunk", "records", "stack"):
        return []
    if target.transform == "regex":
        return [] if target.each else None
    if target.transform in ("pattern_map", "key_value"):
        return {}
    if target.transform == "positional":
        return [] if target.wrap == "list" else None
    return None


def _build_target(csq_values, index_map, target: TargetSpec):
    if not _when_holds(csq_values, index_map, target.when):
        return _empty_value(target)

    if target.transform == "zip":
        return _apply_zip(csq_values, index_map, target)
    if target.transform == "regex":
        return _apply_regex(csq_values, index_map, target)
    if target.transform == "pattern_map":
        return _apply_pattern_map(csq_values, index_map, target)
    if target.transform == "chunk":
        return _apply_chunk(csq_values, index_map, target)
    if target.transform == "positional":
        return _apply_positional(csq_values, index_map, target)
    if target.transform == "key_value":
        return _apply_key_value(csq_values, index_map, target)
    if target.transform == "records":
        return _apply_records(csq_values, index_map, target)
    if target.transform == "stack":
        return _apply_stack(csq_values, index_map, target)

    raw = _column(csq_values, target.source, index_map)
    if target.transform == "scalar":
        return _coerce(raw, target.type)
    if target.transform == "list":
        return split_amp(raw, target.sep)
    if target.transform == "first":
        return _coerce(first_amp(raw, target.sep), target.type)
    raise ValueError(f"unknown transform: {target.transform}")


def _decode_leaves(value, memo: dict | None = None):
    """Percent-decode every string leaf of a produced value.

    `unquote`, never `unquote_plus`: '+' is a structural separator in the
    enriched ClinVar VCF, not an encoded space.

    `memo` keys decoded containers by identity, because a join attaches the
    *same* row objects to more than one place: a submission is reachable both
    as `submissions[i]` and as `conditions[j].classifications[k].submitters[l]`.
    Decoding the output as one tree therefore walked each of those records once
    per path — measured at twice the decode work on ClinVar, and it also broke
    the sharing, so the response carried two copies of every submission. With
    the memo each container is decoded once and stays shared.
    """
    if isinstance(value, str):
        return unquote(value)
    if not isinstance(value, (list, dict)):
        return value
    memo = {} if memo is None else memo
    seen = memo.get(id(value))
    if seen is not None:
        return seen
    if isinstance(value, list):
        decoded = [_decode_leaves(v, memo) for v in value]
    else:
        decoded = {k: _decode_leaves(v, memo) for k, v in value.items()}
    memo[id(value)] = decoded
    return decoded


def _apply_target(csq_values, index_map, target: TargetSpec):
    """One target's value, still encoded.

    Decoding is deliberately *not* done here. It is the last step of
    `apply_plugin_spec`, after the joins, because a join splits on a separator
    too: decoding a target as it was built left the join splitting text that had
    already been decoded, so an escaped separator inside a value — a condition
    literally named `Foo+Bar` — was read as a real one and its rows silently
    vanished. One decode point, after every split, is the only arrangement in
    which that cannot happen.
    """
    return _build_target(csq_values, index_map, target)


def _join_key(value, pattern, case_insensitive: bool) -> str | None:
    """The comparable form of a key: the `key` group of `pattern` if it matches,
    else the value as it stands. A value the pattern rejects still keys on
    itself rather than vanishing."""
    if value is None:
        return None
    key = str(value)
    if pattern:
        match = re.search(pattern, key)
        if match and match.groupdict().get("key") is not None:
            key = match.group("key")
    return key.casefold() if case_insensitive else key


def _apply_joins(built: dict, joins) -> None:
    """Stitch the plugin's lists together in place (see JoinSpec)."""
    for join in joins or []:
        left = built.get(join.into)
        right = built.get(join.source)
        if not isinstance(left, list) or not isinstance(right, list):
            continue
        buckets: dict[str, list] = {}
        for row in right:
            raw_key = row.get(join.right_key)
            parts = (
                str(raw_key).split(join.right_key_sep)
                if join.right_key_sep and raw_key is not None
                else [raw_key]
            )
            for part in parts:
                key = _join_key(part, join.right_key_pattern, join.case_insensitive)
                if key is not None:
                    buckets.setdefault(key, []).append(row)
        for row in left:
            key = _join_key(row.get(join.left_key), None, join.case_insensitive)
            matches = buckets.get(key, []) if key is not None else []
            # A key can be ambiguous on its own (one condition name under two
            # classification types); the extra equalities disambiguate it.
            for left_field, right_field in (join.also_match or {}).items():
                wanted = _join_key(row.get(left_field), None, join.case_insensitive)
                matches = [
                    match
                    for match in matches
                    if _join_key(
                        match.get(right_field), None, join.case_insensitive
                    )
                    == wanted
                ]
            # `where` narrows the matches rather than the buckets, so a count
            # can still tell "none of them qualified" from "there were none" —
            # and two joins differing only by `where` share one bucket map.
            candidates = matches
            if join.where is not None:
                matches = [
                    match
                    for match in matches
                    if str(match.get(join.where.field)) == join.where.equals
                ]
            if join.count_into:
                # No candidates at all means there is nothing to report, not a
                # count of zero: "0 of 0 submissions" is a sentence about
                # nothing. A real zero — none of several qualifying — is kept.
                row[join.count_into] = len(matches) if candidates else None
            elif join.count_by:
                groups: dict[str, list] = {}
                for match in matches:  # first-seen order
                    value = match.get(join.count_by)
                    if value is not None:
                        groups.setdefault(value, []).append(match)
                row[join.as_field] = [
                    {
                        join.count_by: value,
                        "count": len(members),
                        # The rows the count was made of, kept beside it rather
                        # than left for the display to re-group.
                        **({join.nest_as: members} if join.nest_as else {}),
                    }
                    for value, members in groups.items()
                ]
            else:
                row[join.as_field] = matches


def _row_in_scope(csq_values, index_map, scope) -> bool:
    """Whether this CSQ row is one the plugin's annotation belongs to.

    True when there is nothing to narrow by — see RowScope: a row with no value
    of its own, or an annotation naming nothing, keeps the annotation rather
    than losing it.
    """
    if scope is None:
        return True
    listed = _column(csq_values, scope.listed_in, index_map)
    value = _column(csq_values, scope.column, index_map)
    if not listed or not value:
        return True
    # Split on the separator first, decode after: an escaped separator inside a
    # name must not be read as one (the house rule for this VCF).
    names = {
        _join_key(unquote(entry), scope.item_pattern, False)
        for entry in listed.split(scope.sep)
        if entry
    }
    return value in names


def apply_plugin_spec(
    csq_values: list[str],
    index_map: dict[str, int],
    spec: PluginSpec,
    cache: dict | None = None,
) -> dict | None:
    """One plugin's annotation for this CSQ entry, or None if there is nothing.

    None means "no annotation", matching the hand-written parsers: either the
    plugin's columns are absent from the header (it never ran), or they are
    present but this record has no values in them.
    """
    if not has_any_column(index_map, *spec.csq_fields):
        return None

    if not _row_in_scope(csq_values, index_map, spec.applies_to):
        return None

    # A plugin reads only its own columns, and VEP repeats those on every CSQ
    # row of a variant — so the annotation is the same for all of them, and a
    # transcript-scoped plugin was parsing it once per row to get one answer.
    # ClinVar did that 936 times over a 50-record file to produce 61 distinct
    # results. Keyed on the columns the plugin actually reads, so two rows that
    # differ only in the ones it ignores share the work. The row gate above is
    # deliberately outside this: it is what legitimately differs per row.
    key = None
    if cache is not None:
        key = (spec.plugin, tuple(_column(csq_values, c, index_map)
                                  for c in spec.csq_fields))
        if key in cache:
            return cache[key]

    # Raw presence, deliberately: a literal 'NA' counts as present here, which
    # is what the hand-written parsers do.
    if spec.require_any_input and not any(
        _column(csq_values, column, index_map) for column in spec.require_any_input
    ):
        return None

    output = {
        target.field: _apply_target(csq_values, index_map, target)
        for target in spec.targets
    }
    # Every target reads one column, so a source spreading one logical table
    # across several columns is only whole after they are stitched together.
    _apply_joins(output, spec.joins)
    # Ordering by what a join added has to wait for the joins (see JoinedPostOp).
    for operation in spec.post_joins or []:
        rows = output.get(operation.target)
        if isinstance(rows, list):
            output[operation.target] = _apply_post(rows, [operation])

    # Every split has now run — the targets' own and the joins' — so an encoded
    # separator can no longer be mistaken for one (see `_apply_target`).
    decoded: dict = {}
    for target in spec.targets:
        if target.decode:
            output[target.field] = _decode_leaves(output[target.field], decoded)

    if spec.require_any_output and not any(
        _is_present(output.get(field)) for field in spec.require_any_output
    ):
        output = None

    # The join sources have done their work. `_apply_joins` attached the very
    # same row objects where they are actually read -- a submission under the
    # condition it was filed against -- so keeping the flat lists as well
    # shipped every submission twice, 40% of ClinVar's payload. Dropped last, so
    # decoding and `require_any_output` still see them.
    if output is not None:
        for target in spec.targets:
            if target.join_source:
                output.pop(target.field, None)

    if key is not None:
        cache[key] = output
    return output
