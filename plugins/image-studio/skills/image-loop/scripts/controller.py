"""Pure review policy shared by the CLI and offline tests.

Action names and their order match image-verify's audit_candidate.decide;
see image-verify/references/decisions.md.
"""
import json


def dependency_errors(brief):
    """A criterion may depend only on other known criteria, without cycles."""
    ids = {c['id'] for c in brief['criteria']}
    parents = {c['id']: c.get('depends_on', []) for c in brief['criteria']}
    for child, deps in parents.items():
        if len(deps) != len(set(deps)):
            return [f'Criterion {child} repeats a depends_on ID.']
        for dep in deps:
            if dep == child:
                return [f'Criterion {child} depends on itself.']
            if dep not in ids:
                return [f'Criterion {child} depends on unknown criterion {dep}.']
    # Kahn's algorithm: iterative, so a long chain cannot hit the recursion limit.
    waiting = {node: len(set(deps)) for node, deps in parents.items()}
    children = {node: [] for node in parents}
    for node, deps in parents.items():
        for dep in set(deps):
            children[dep].append(node)
    ready = [node for node, n in waiting.items() if n == 0]
    done = 0
    while ready:
        node = ready.pop()
        done += 1
        for child in children[node]:
            waiting[child] -= 1
            if waiting[child] == 0:
                ready.append(child)
    if done != len(parents):
        return ['Brief depends_on links form a cycle.']
    return []


def coverage_errors(brief, report):
    expected = [c['id'] for c in brief['criteria']]
    actual = [c['id'] for c in report['criteria']]
    if len(expected) != len(set(expected)):
        return ['Brief criterion IDs must be unique.']
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        return ['Review must cover every criterion exactly once, with no invented IDs.']
    if any(not c['evidence'].strip() for c in report['criteria']):
        return ['Every verdict needs visible evidence or a reason it is uncertain.']
    return []


def ancestors(brief, cid):
    parents = {c['id']: c.get('depends_on', []) for c in brief['criteria']}
    seen, todo = set(), list(parents.get(cid, []))
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo += parents.get(node, [])
    return seen


def focus_of(brief, failing):
    """One failure per repair round: a failure whose prerequisites all pass, protected first, then brief order."""
    failing = set(failing)
    roots = [c for c in brief['criteria'] if c['id'] in failing and not ancestors(brief, c['id']) & failing]
    roots.sort(key=lambda c: c['kind'] != 'protected')
    return roots[0]['id'] if roots else None


def decide(brief, report, checks, repairs_used=0, max_repairs=3, previous=None):
    errors = dependency_errors(brief) + coverage_errors(brief, report)
    if previous is not None:
        errors += coverage_errors(brief, previous)
    if errors:
        return {'action': 'stop_invalid_review', 'reason': ' '.join(errors)}
    if repairs_used < 0 or max_repairs < 0:
        raise ValueError('Repair counts must be nonnegative.')
    failing = [c for c in report['criteria'] if c['status'] == 'fail']
    uncertain = [c for c in report['criteria'] if c['status'] == 'uncertain']
    if not checks['passed']:
        return {'action': 'reject_technical', 'reason': 'Resolve output-file failures before acceptance or further generative edits.',
                'issues': checks['failures']}
    if uncertain:
        return {'action': 'hold_for_inspection', 'reason': 'Uncertain evidence requires stronger inspection.',
                'ids': [c['id'] for c in uncertain]}
    if not failing:
        return {'action': 'accepted_by_checks', 'reason': 'All requested and protected criteria and file checks passed.', 'ids': []}
    if repairs_used >= max_repairs:
        return {'action': 'stop_budget', 'reason': 'Repair limit reached.', 'ids': [c['id'] for c in failing]}
    if previous is not None and repairs_used > 0:
        old = {c['id'] for c in previous['criteria'] if c['status'] == 'fail'}
        if old == {c['id'] for c in failing}:
            return {'action': 'stop_repeated_failure', 'reason': 'Same failure set persisted after a repair.', 'ids': sorted(old)}
    failed_ids = [c['id'] for c in failing]
    protected = {c['id'] for c in brief['criteria'] if c['kind'] == 'protected'}
    regressed = []
    if previous is not None:
        passed_before = {c['id'] for c in previous['criteria'] if c['status'] == 'pass'}
        regressed = [i for i in failed_ids if i in passed_before]
    protected_failed = [i for i in failed_ids if i in protected]
    if regressed:
        # This candidate broke something that already passed: retry the previous focus on the previous start image.
        base = previous
        focus = focus_of(brief, [c['id'] for c in previous['criteria'] if c['status'] == 'fail']) or focus_of(brief, failed_ids)
        start_from = 'previous start image (the one the last repair edited); never this candidate'
    elif protected_failed:
        base = None
        focus = focus_of(brief, failed_ids)
        start_from = 'clean source; never this candidate because protected_failed is not empty'
    else:
        base = report
        focus = focus_of(brief, failed_ids)
        start_from = 'this candidate'
    decision = {'action': 'repair', 'reason': 'Repair one failed requirement (focus) per round; recheck all criteria.',
                'ids': failed_ids, 'focus': focus,
                'blocked': [i for i in failed_ids if ancestors(brief, i) & set(failed_ids)],
                'regressed': regressed,
                'protected_failed': protected_failed,
                'start_from': start_from}
    # Verdicts for the image the next repair edits; the next round compares against these.
    # The clean source was never reviewed against the brief, so after a restart there is nothing to compare.
    decision['start_review'] = {'criteria': base['criteria'], 'summary': base.get('summary', '')} if base else None
    return decision


def repair_prompt(brief, report, decision):
    if decision['action'] != 'repair':
        return ''
    focus = decision['focus']
    by_id = {c['id']: c for c in brief['criteria']}
    base = decision['start_review']
    c, r = by_id[focus], {x['id']: x for x in (base or report)['criteria']}[focus]
    if base is None:
        # Restarting from the clean source: nothing from the rejected candidate carries over.
        requested = [x for x in brief['criteria'] if x['kind'] == 'requested']
        lines = ['Edit the supplied clean source image according to this brief:', brief['intent'],
                 '', 'The previous attempt damaged a protected part; avoid this observed failure:',
                 f"- {c['id']} ({c['target']}): {c['requirement']}",
                 f"  Reviewer observation: {r['evidence']}"]
        if requested:
            lines += ['', 'Apply these requested changes:'] + [f"- {x['id']}: {x['requirement']}" for x in requested]
        lines += ['', 'Keep these exactly as in the source:']
        lines += [f"- {x['id']}: {x['requirement']}" for x in brief['criteria'] if x['kind'] == 'protected']
    else:
        status = {x['id']: x['status'] for x in base['criteria']}
        lines = ['Edit the supplied image according to this brief:', brief['intent'],
                 '', 'Correct this one observed failure:',
                 f"- {c['id']} ({c['target']}): {c['requirement']}",
                 f"  Reviewer observation: {r['evidence']}",
                 f"  Suggested minimal fix: {r['suggested_fix']}"]
        if decision.get('regressed'):
            lines += ['', 'The last attempt at this broke: ' + ', '.join(decision['regressed']) + '. Keep them intact this time.']
        later = [x for x in brief['criteria'] if x['id'] != focus and status[x['id']] == 'fail']
        if later:
            lines += ['', 'Leave these known failures for later rounds; do not work on them now:']
            lines += [f"- {x['id']}: {x['requirement']}" for x in later]
        keep = [x for x in brief['criteria'] if x['id'] != focus and status[x['id']] == 'pass']
        if keep:
            lines += ['', 'Keep every requirement below exactly as it is now; do not introduce unrelated improvements:']
            lines += [f"- {x['id']}: {x['requirement']}" for x in keep]
    lines += ['', 'Output file requirements: '+json.dumps(brief['file_checks']),
              'Do not add review badges, numbering, or annotation arrows.',
              'If source and candidate are both supplied, use the source for preserved appearance and the stated edit for changes.']
    return '\n'.join(lines)+'\n'
