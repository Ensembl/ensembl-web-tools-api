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
        drop = field_spec.drop_entries
        if drop is not None:
            kept = [
                entry
                for entry in raw.split(drop.sep)
                if not re.search(drop.matching, entry)
            ]
            # Nothing left is nothing to say: an empty packed string would reach
            # the display as a value and draw an empty cell.
            if not kept:
                return None
            raw = drop.sep.join(kept)
    return raw


def _column(csq_values: list[str], name: str, index_map: dict[str, int]) -> str | None:
    return get_csq_value(csq_values, name, None, index_map)


def _same(value, expected) -> bool:
    """Compare populated values as text, as spec literals have no Python type."""
    if value is None or expected is None or expected == "":
        return False
    return str(value) == str(expected)


def _matches(row: dict, match, csq_values=None, index_map=None) -> bool:
    """Whether a produced element satisfies one `Match` (see the model)."""
    if match.equals_column is not None:
        expected = (
            _column(csq_values, match.equals_column, index_map)
            if csq_values is not None and index_map is not None
            else None
        )
        if expected is not None and match.column_pattern:
            found = re.search(match.column_pattern, str(expected))
            # A missing capture is treated as an absent comparison value.
            expected = found.group("key") if found else None
    else:
        expected = match.equals
    return _same(row.get(match.field), expected)


def _should_drop(row: dict, drop_when, csq_values=None, index_map=None) -> bool:
    if drop_when is None:
        return False
    # Restrict the discard rule to elements matching its optional condition.
    condition = drop_when.only_if
    if condition is not None and not _matches(row, condition, csq_values, index_map):
        return False
    if drop_when.all_null:
        return all(value is None for value in row.values())
    if drop_when.unless_matches is not None:
        return not _matches(row, drop_when.unless_matches, csq_values, index_map)
    return row.get(drop_when.null) is None


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@lru_cache(maxsize=None)
def _lookup_table(name: str) -> dict[str, str]:
    """Load a shipped lookup table as a string-keyed value-to-label mapping.

    Tables may be grouped by label or stored under a flat `terms` mapping.
    """
    path = DATA_DIR / f"{name}.json"
    document = json.loads(path.read_text())
    if "terms" in document:
        return {str(key): label for key, label in document["terms"].items()}
    return {
        str(member): label for label, members in document.items() for member in members
    }


def _lookup_key(value) -> str | None:
    """Normalise a parsed identifier for a shipped lookup table."""
    if not isinstance(value, str):
        return None
    head, sep, tail = value.partition(":")
    if not sep:
        return head or None
    if not tail:
        return None
    return str(int(tail)) if tail.isdigit() else tail


def _fill_template(template: str, row: dict) -> str | None:
    """Fill a URL template, returning None when a referenced field is empty."""
    filled = template
    for name in re.findall(r"\{(\w+)\}", template):
        value = row.get(name)
        if value in (None, ""):
            return None
        filled = filled.replace("{" + name + "}", str(value))
    return filled


def _resolve_curie(value, prefer, templates, sep):
    """Return the preferred usable URL and CURIE from a separator-delimited list."""
    if not value:
        return None, None
    # ClinVar encodes this list's separator, so decode before splitting.
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
        if operation.op == "split_field":
            for row in rows:
                raw = row.get(operation.by)
                if raw is None or raw == "":
                    row[operation.into] = None
                    continue
                before, found, after = str(raw).partition(operation.sep)
                # No separator means the field is all of one part and none of
                # the other, rather than "the whole thing, twice": a MaveDB
                # accession with no '#' names a score set and no variant within
                # it, so the variant half must come out empty and drop its link.
                row[operation.into] = (
                    before if operation.keep == "before" else (after if found else None)
                )
            continue
        if operation.op == "derive_if_empty":
            compiled = re.compile(operation.pattern)
            for row in rows:
                if row.get(operation.into):
                    continue
                raw = row.get(operation.by)
                if not raw:
                    continue
                built = []
                for entry in str(raw).split(operation.sep or "+"):
                    match = compiled.match(entry)
                    if match:
                        built.append(
                            {k: v for k, v in match.groupdict().items()}
                        )
                if built:
                    row[operation.into] = built
            continue
        if operation.op == "default":
            for row in rows:
                if row.get(operation.by) in (None, ""):
                    row[operation.by] = operation.value
            continue
        if operation.op == "only_if_differs":
            def _leaves(row, path):
                """Every element at a dotted path, however deep."""
                nodes = [row]
                for step in path.split("."):
                    nxt = []
                    for node in nodes:
                        value = node.get(step) if isinstance(node, dict) else None
                        if isinstance(value, list):
                            nxt.extend(value)
                        elif value is not None:
                            nxt.append(value)
                    nodes = nxt
                return nodes

            for row in rows:
                shown = {
                    str(v).casefold()
                    for v in _leaves(row, operation.against)
                    if not isinstance(v, (dict, list))
                }
                # Copy: a join attaches the same object to every row it matched,
                # so writing through it would mark the others too.
                holder, _, last = operation.in_.rpartition(".")
                for parent in _leaves(row, holder) if holder else [row]:
                    if not isinstance(parent, dict):
                        continue
                    items = parent.get(last)
                    if not isinstance(items, list):
                        continue
                    parent[last] = [
                        {
                            **item,
                            operation.into: (
                                item.get(operation.field)
                                if str(item.get(operation.field)).casefold() not in shown
                                and item.get(operation.field) is not None
                                else None
                            ),
                        }
                        if isinstance(item, dict)
                        else item
                        for item in items
                    ]
            continue
        if operation.op == "collapse":
            # Rows identical but for `fields` are one row with those fields
            # gathered. Keyed on everything else, so what "identical" means is
            # the whole of the rest of the row rather than a list somebody has
            # to keep in step.
            varying = list(operation.fields or [])
            groups: dict[str, dict] = {}
            for row in rows:
                key = json.dumps(
                    {k: v for k, v in row.items() if k not in varying},
                    sort_keys=True,
                    default=str,
                )
                group = groups.get(key)
                if group is None:
                    group = {k: v for k, v in row.items() if k not in varying}
                    group[operation.into] = []
                    groups[key] = group
                group[operation.into].append(
                    {field: row.get(field) for field in varying}
                )
            rows = list(groups.values())  # first-seen order
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
        if operation.op == "mapped_link":
            for row in rows:
                key = row.get(operation.by)
                template = operation.templates.get(str(key)) if key else None
                # An unmapped source, or a template naming a field this row left
                # empty, means no link rather than a broken one: the phenotype
                # then renders as plain text. `id` and `external_id` are both
                # offered because which addresses the record differs by source.
                row[operation.into] = (
                    _fill_template(template, row) if template else None
                )
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


def _apply_pattern_map(csq_values, index_map, target: TargetSpec, columns=None) -> dict:
    """Columns matching `from_pattern` -> {wildcard: value}.

    The columns are discovered from the CSQ header, so whichever ancestries a
    run actually emitted come through without being named in the spec. That
    discovery depends only on the header, so `columns` carries it precomputed
    (see PluginPlan); without one it is rediscovered here, which is what a
    caller holding only an index_map gets.
    """
    if columns is None:
        columns = _pattern_columns(index_map, target)

    values: dict = {}
    for key, index in columns:
        # `or None` keeps the empty column reading as absent, as `_column` did.
        value = _coerce(csq_values[index] or None, target.type)
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
    """Fixed-size groups of '&'-items -> a list of objects.

    `record_sep` divides the value into objects first, and each is then chunked
    on its own. Both levels are read because ProtVar publishes both: it used to
    write one flat run of items, and now separates its pockets with '+'. Cutting
    a flat run every `size` is only right while every object is exactly that
    long — one short record shifts every later object's fields along by the
    difference — so where the source marks the boundary, it is honoured, and a
    malformed record damages only itself.
    """
    raw = _column(csq_values, target.source, index_map)
    if not raw:
        return _apply_post([], target.post)
    records = raw.split(target.record_sep) if target.record_sep else [raw]

    rows = []
    for record in records:
        tokens = record.split(target.sep)
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
    return when.includes in _listed_keys(
        _column(csq_values, when.field, index_map), when.sep, when.item_pattern
    )


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


def _build_target(csq_values, index_map, target: TargetSpec, plan=None):
    if not _when_holds(csq_values, index_map, target.when):
        return _empty_value(target)

    if target.transform == "zip":
        return _apply_zip(csq_values, index_map, target)
    if target.transform == "regex":
        return _apply_regex(csq_values, index_map, target)
    if target.transform == "pattern_map":
        return _apply_pattern_map(
            csq_values,
            index_map,
            target,
            plan.pattern_columns.get(target.field) if plan else None,
        )
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


def _apply_target(csq_values, index_map, target: TargetSpec, plan=None):
    """One target's value, still encoded.

    Decoding is deliberately *not* done here. It is the last step of
    `apply_plugin_spec`, after the joins, because a join splits on a separator
    too: decoding a target as it was built left the join splitting text that had
    already been decoded, so an escaped separator inside a value — a condition
    literally named `Foo+Bar` — was read as a real one and its rows silently
    vanished. One decode point, after every split, is the only arrangement in
    which that cannot happen.
    """
    return _build_target(csq_values, index_map, target, plan)


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


def _left_keys(row: dict, join) -> list[str]:
    """The key(s) a left row joins on — usually one, sometimes several.

    A left row can be about more than one thing. A dotted `left_key` reads a
    subfield of a list the row already carries, and `left_key_sep` splits a
    field that packs several values into one string, with `left_key_pattern`
    taking the comparable part of each — the mirror of the right-hand options.

    ClinVar needs both: a submission is filed under one RCV, and an RCV covers
    up to five conditions listed as `MedGen:C0266313:Renal_tubular_dysgenesis`
    in a single '+'-joined field.
    """
    field, _, sub = join.left_key.partition(".")
    value = row.get(field)
    values = (
        [item.get(sub) for item in value or [] if isinstance(item, dict)]
        if sub
        else [value]
    )
    if join.left_key_sep:
        values = [
            part
            for raw in values
            for part in (str(raw).split(join.left_key_sep) if raw is not None else [])
        ]
    keys = []
    for raw in values:
        key = _join_key(raw, join.left_key_pattern, join.case_insensitive)
        if key is not None and key not in keys:
            keys.append(key)
    return keys


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
            matches = []
            for key in _left_keys(row, join):
                for candidate in buckets.get(key, []):
                    # A row reachable by two keys is still one match.
                    if not any(candidate is seen for seen in matches):
                        matches.append(candidate)
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
                    if _matches(match, join.where)
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


def _listed_keys(listed: str | None, sep: str, item_pattern: str | None) -> set[str]:
    """The comparable entries of a column that packs a list.

    Split on the separator first, decode after: an escaped separator inside a
    name must not be read as one (the house rule for this VCF). `item_pattern`
    takes the comparable part of each entry via a `key` group, as a join's
    `right_key_pattern` does.

    Shared by `applies_to` and a target's `when`, which are the same membership
    test asked in two places -- and were two implementations, which is how
    `when` came to be missing the separator and pattern that `applies_to` grew.
    """
    if not listed:
        return set()
    return {
        _join_key(unquote(entry), item_pattern, False)
        for entry in listed.split(sep)
        if entry
    }


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
    return value in _listed_keys(listed, scope.sep, scope.item_pattern)


class PluginPlan:
    """One plugin resolved against one CSQ header.

    Everything here depends only on the header, which is fixed for the whole
    file — yet all of it used to be recomputed per CSQ row, by name. Over a
    representative 50-record run that was 21k `has_any_column` calls asking the same
    question, 88k `_column` reads building cache keys, and a 283-column scan per
    `pattern_map` target per allele (~86k `startswith`). Resolving once per file
    and reading by position is what takes the header work off the per-row path.

    `runnable` is False when none of the plugin's columns are in the header —
    the plugin never ran, so it can be skipped for every row of the file rather
    than gated on each one.
    """

    __slots__ = ("runnable", "key_indices", "input_indices", "pattern_columns")

    def __init__(self, runnable, key_indices, input_indices, pattern_columns):
        self.runnable = runnable
        self.key_indices = key_indices
        self.input_indices = input_indices
        self.pattern_columns = pattern_columns


def _pattern_columns(
    index_map: dict[str, int], target: TargetSpec
) -> tuple[tuple[str, int], ...]:
    """The header columns a `pattern_map` target matches, as (wildcard, index).

    Same scan `_apply_pattern_map` did per row, and in the same order, so the
    resulting dict is built identically — only now it happens once per file.
    """
    prefix, suffix = pattern_affixes(target.from_pattern)
    excluded = set(target.exclude or [])
    return tuple(
        (column[len(prefix): len(column) - len(suffix)], index)
        for column, index in index_map.items()
        if column not in excluded
        and column.startswith(prefix)
        and column.endswith(suffix)
    )


def _match_columns(spec: PluginSpec) -> list[str]:
    """Every CSQ column a predicate of this plugin compares against.

    These belong in the cache key even though the plugin does not *read* them as
    input. The key exists because a plugin's output is the same on every CSQ row
    of a variant — true while it depends only on its own columns, and false the
    moment a `drop_when` narrows the output against a column that varies per row.

    `Gene` is exactly that case: two rows carrying identical `PHENOTYPES` produce
    different results, and keying on `PHENOTYPES` alone would serve the first
    row's answer to every later one — the very mis-attribution the rule removes,
    now invisible. (`applies_to` needs no entry here: it is evaluated *before*
    the cache, which is why ClinVar's row gate has always been correct.)
    """
    columns: list[str] = []
    for target in spec.targets:
        drop_when = target.drop_when
        if drop_when is None:
            continue
        for match in (drop_when.unless_matches, drop_when.only_if):
            if match is not None and match.equals_column:
                columns.append(match.equals_column)
    for join in spec.joins or []:
        if join.where is not None and join.where.equals_column:
            columns.append(join.where.equals_column)
    return columns


def compile_plugin(index_map: dict[str, int], spec: PluginSpec) -> PluginPlan:
    """Resolve one plugin against a CSQ header. See PluginPlan."""
    # Deduplicated, and in declaration order, so the key is stable across runs.
    key_columns = list(dict.fromkeys([*spec.csq_fields, *_match_columns(spec)]))
    return PluginPlan(
        runnable=has_any_column(index_map, *spec.csq_fields),
        # Absent columns simply drop out: `_column` returned None for them, so
        # they never distinguished one row from another anyway.
        key_indices=tuple(
            index_map[column] for column in key_columns if column in index_map
        ),
        input_indices=tuple(
            index_map[column]
            for column in (spec.require_any_input or [])
            if column in index_map
        ),
        pattern_columns={
            target.field: _pattern_columns(index_map, target)
            for target in spec.targets
            if target.transform == "pattern_map"
        },
    )


def compile_parsing_spec(index_map: dict[str, int], spec) -> dict[str, PluginPlan]:
    """Every plugin in a parsing spec resolved against a CSQ header, by plugin
    name. Build once per file and thread down; see PluginPlan."""
    return {plugin.plugin: compile_plugin(index_map, plugin) for plugin in spec.plugins}


def apply_plugin_spec(
    csq_values: list[str],
    index_map: dict[str, int],
    spec: PluginSpec,
    cache: dict | None = None,
    plan: PluginPlan | None = None,
) -> dict | None:
    """One plugin's annotation for this CSQ entry, or None if there is nothing.

    None means "no annotation", matching the hand-written parsers: either the
    plugin's columns are absent from the header (it never ran), or they are
    present but this record has no values in them.

    `plan` is this plugin resolved against the header (see PluginPlan). It is
    optional so a caller with only an index_map still works; pass one built once
    per file to keep the header work out of the per-row path.
    """
    if plan is None:
        plan = compile_plugin(index_map, spec)

    if not plan.runnable:
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
        key = (spec.plugin, tuple(csq_values[i] for i in plan.key_indices))
        if key in cache:
            return cache[key]

    # Raw presence, deliberately: a literal 'NA' counts as present here, which
    # is what the hand-written parsers do.
    if spec.require_any_input and not any(
        csq_values[i] for i in plan.input_indices
    ):
        return None

    output = {
        target.field: _apply_target(csq_values, index_map, target, plan)
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
