#!/usr/bin/env node
// pr-merge-watch: read-only watcher for the pr-merge-loop skill.
//
//   node pr-merge-watch.mjs status <PR> [--repo owner/name]
//   node pr-merge-watch.mjs wait   <PR> [--repo owner/name] [--no-auto] [--skip-ok]
//                                       [--interval 60] [--timeout 0] [--grace 600]
//
// --no-auto: the agent merges by itself once a person approved the head (no auto-merge). It is
//   implied when the PR's last `step=open` marker says `mode=manual`.
// --no-review: as --no-auto, but the user waived the review: ready once every check passed.
//   Implied by `mode=unreviewed`.
// --skip-ok[=check,...]: a required check that only ever SKIPPED is what this repository intends
//   (e.g. a path filter), not CI that failed to start. Without names it applies to every check.
//
// `status` prints one JSON snapshot of the pull request. `wait` polls until something
// needs the agent (a required check failed, a reviewer wrote, the branch fell behind,
// the PR merged, ...) and then prints the same snapshot with `event` set. It never
// changes the pull request: every push, comment and merge stays an explicit command
// of the agent. All state lives in the PR itself, so a new session can run it again.
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

const MARKER_RE = /<!--\s*pr-review-loop\s+([^>]*?)\s*-->/;
// gh merges at once instead of arming auto-merge when the PR is in one of these states.
const IMMEDIATELY_MERGEABLE = new Set(["CLEAN", "HAS_HOOKS", "UNSTABLE"]);
const BODY_LIMIT = 3000;
// Polling faster than this only burns API quota; the tests lower it to keep themselves short.
const MIN_INTERVAL = Number(process.env.PR_MERGE_WATCH_MIN_INTERVAL) || 15;

const QUERY = `
query($owner:String!,$name:String!,$number:Int!){
  viewer{login}
  repository(owner:$owner,name:$name){
    nameWithOwner autoMergeAllowed mergeCommitAllowed squashMergeAllowed rebaseMergeAllowed viewerDefaultMergeMethod
    pullRequest(number:$number){
      number url title state isDraft mergeable mergeStateStatus reviewDecision
      headRefOid headRefName baseRefName isInMergeQueue mergedAt
      mergeCommit{oid}
      author{login}
      autoMergeRequest{enabledAt mergeMethod enabledBy{login}}
      baseRef{branchProtectionRule{requiredApprovingReviewCount requiresStatusChecks requiredStatusCheckContexts requiresStrictStatusChecks requiresConversationResolution dismissesStaleReviews}}
      reviewRequests(first:30){nodes{requestedReviewer{__typename ... on User{login} ... on Bot{login} ... on Mannequin{login} ... on Team{slug}}}}
      latestOpinionatedReviews(first:50){nodes{author{__typename login} state commit{oid}}}
      latestReviews(first:50){nodes{author{login} state}}
      timelineItems(last:10,itemTypes:[AUTO_MERGE_ENABLED_EVENT,AUTO_SQUASH_ENABLED_EVENT,AUTO_REBASE_ENABLED_EVENT,AUTO_MERGE_DISABLED_EVENT]){nodes{
        __typename
        ... on AutoMergeEnabledEvent{actor{login}}
        ... on AutoSquashEnabledEvent{actor{login}}
        ... on AutoRebaseEnabledEvent{actor{login}}
        ... on AutoMergeDisabledEvent{actor{login} reasonCode}
      }}
      reviews(last:100){nodes{url state body submittedAt author{__typename login}}}
      reviewThreads(last:100){nodes{id isResolved isOutdated path line comments(last:6){nodes{url body createdAt publishedAt author{__typename login}}}}}
      comments(last:100){pageInfo{hasPreviousPage startCursor} nodes{url body createdAt author{__typename login}}}
      commits(last:1){nodes{commit{oid statusCheckRollup{state contexts(first:100){pageInfo{hasNextPage endCursor} nodes{...Ctx}}}}}}
    }
  }
}
fragment Ctx on StatusCheckRollupContext{
  __typename
  ... on CheckRun{name status conclusion detailsUrl startedAt isRequired(pullRequestNumber:$number) checkSuite{workflowRun{databaseId event workflow{name}}}}
  ... on StatusContext{context state targetUrl createdAt isRequired(pullRequestNumber:$number)}
}`;

const MORE_CHECKS_QUERY = `
query($owner:String!,$name:String!,$number:Int!,$after:String!){
  repository(owner:$owner,name:$name){pullRequest(number:$number){
    commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{...Ctx}}}}}}
  }}
}
fragment Ctx on StatusCheckRollupContext{
  __typename
  ... on CheckRun{name status conclusion detailsUrl startedAt isRequired(pullRequestNumber:$number) checkSuite{workflowRun{databaseId event workflow{name}}}}
  ... on StatusContext{context state targetUrl createdAt isRequired(pullRequestNumber:$number)}
}`;

const OLDER_COMMENTS_QUERY = `
query($owner:String!,$name:String!,$number:Int!,$before:String!){
  repository(owner:$owner,name:$name){pullRequest(number:$number){
    comments(last:100,before:$before){pageInfo{hasPreviousPage startCursor} nodes{url body createdAt author{__typename login}}}
  }}
}`;

// ---------------------------------------------------------------- pure logic

/** Parse the `<!-- pr-review-loop step=.. round=.. sha=.. until=.. -->` marker of a comment. */
export function parseMarker(body) {
  const m = MARKER_RE.exec(body || "");
  if (!m) return null;
  const out = {};
  for (const pair of m[1].split(/\s+/)) {
    const i = pair.indexOf("=");
    if (i > 0) out[pair.slice(0, i)] = pair.slice(i + 1);
  }
  return out.step ? out : null;
}

const ts = v => (v ? Date.parse(v) || 0 : 0);
const trim = s => {
  const t = (s || "").trim();
  return t.length > BODY_LIMIT ? t.slice(0, BODY_LIMIT) + `\n…(${t.length - BODY_LIMIT} more characters, open the url)` : t;
};

/**
 * Map raw rollup contexts to one entry per check (workflow, event, name).
 * A head commit often carries several runs of the same check: re-runs, and runs that label or
 * comment events add and that end SKIPPED or CANCELLED without testing anything. The entry is the
 * latest run that actually decided something (passed, failed, or still running); only when no
 * such run exists does a skipped or cancelled one speak for the check.
 */
export function normalizeChecks(nodes) {
  const INCONCLUSIVE = new Set(["SKIPPED", "NEUTRAL", "CANCELLED", "STALE"]);
  const byKey = new Map();
  for (const n of nodes || []) {
    let c;
    if (n.__typename === "CheckRun") {
      const run = n.checkSuite?.workflowRun;
      const done = n.status === "COMPLETED";
      const state = !done ? "pending"
        : n.conclusion === "SUCCESS" ? "pass"
        : n.conclusion === "NEUTRAL" || n.conclusion === "SKIPPED" ? "skip"
        : "fail";
      c = {
        key: `${run?.workflow?.name || ""}|${run?.event || ""}|${n.name}`,
        name: n.name, workflow: run?.workflow?.name || null, state,
        conclusion: done ? n.conclusion : n.status, decided: !(done && INCONCLUSIVE.has(n.conclusion)),
        required: !!n.isRequired, runId: run?.databaseId || null, url: n.detailsUrl || null, at: ts(n.startedAt),
      };
    } else if (n.__typename === "StatusContext") {
      const state = n.state === "SUCCESS" ? "pass" : n.state === "PENDING" || n.state === "EXPECTED" ? "pending" : "fail";
      c = {
        key: `status|${n.context}`, name: n.context, workflow: null, state, conclusion: n.state, decided: true,
        required: !!n.isRequired, runId: null, url: n.targetUrl || null, at: ts(n.createdAt),
      };
    } else continue;
    if (!byKey.has(c.key)) byKey.set(c.key, []);
    byKey.get(c.key).push(c);
  }
  const out = [];
  for (const runs of byKey.values()) {
    const latest = list => list.reduce((a, b) => (b.at >= a.at ? b : a));
    const decided = runs.filter(c => c.decided);
    const { decided: _, ...check } = latest(decided.length ? decided : runs);
    out.push(check);
  }
  return out;
}

/**
 * Decide which checks gate the merge. Required checks gate it when the repository marks any;
 * with no required checks at all, every check counts (nothing tells them apart).
 */
export function summarizeChecks(checks, requiredContexts = [], { skipOk = false } = {}) {
  const required = c => c.required || requiredContexts.includes(c.name);
  const anyRequired = checks.some(required) || requiredContexts.length > 0;
  const gates = c => !anyRequired || required(c);
  const view = c => ({ name: c.name, workflow: c.workflow, conclusion: c.conclusion, runId: c.runId, url: c.url });
  const gating = checks.filter(gates);
  return {
    gating: anyRequired ? "required" : "all",
    total: checks.length,
    passed: gating.filter(c => c.state === "pass" || c.state === "skip").length,
    pending: gating.filter(c => c.state === "pending").map(c => c.name),
    failed: gating.filter(c => c.state === "fail").map(view),
    // Required by the branch rules but not reported on this commit yet (e.g. CI that needs a label or a manual start).
    missingRequired: requiredContexts.filter(n => !checks.some(c => c.name === n)),
    // Required, and every run of it on this commit was SKIPPED. GitHub counts that as passed and will
    // merge on it, but the check never ran (label-gated CI after a push). --skip-ok accepts the skips
    // a repository intends, for all checks or for the named ones.
    skipped: [...new Set(checks.filter(required).map(c => c.name))].filter(name =>
      checks.filter(c => c.name === name).every(c => c.conclusion === "SKIPPED") &&
      !(skipOk === true || (Array.isArray(skipOk) && skipOk.includes(name)))),
    optionalFailed: checks.filter(c => !gates(c) && c.state === "fail").map(view),
  };
}

/**
 * Reviewer feedback that still needs the agent.
 * - A review thread is open while it is unresolved and its last comment is not ours.
 * - A review body or a conversation comment is open while it is newer than the `until`
 *   of our last `step=feedback` marker comment.
 * - Whatever a person wrote before their own latest approval is settled. Comments submitted
 *   with the approval itself ("approve with nits") carry its timestamp and stay open.
 */
export function collectFeedback(pr, viewer) {
  // "Ours" is the account running gh and the PR author (normally the same account).
  const ours = login => login === viewer || login === pr.author?.login;
  // Only our own comments carry state: anyone can type a marker, and a forged `step=open`
  // would read as the user's acceptance.
  const markers = [];
  for (const c of pr.comments?.nodes || []) {
    const m = ours(c.author?.login) ? parseMarker(c.body) : null;
    if (m) markers.push({ ...m, at: c.createdAt, url: c.url });
  }
  const anchor = Math.max(0, ...markers.filter(m => m.step === "feedback").map(m => ts(m.until)));
  const approvedAt = {};
  for (const r of pr.reviews?.nodes || []) {
    if (r.state === "APPROVED") approvedAt[r.author?.login] = Math.max(approvedAt[r.author?.login] || 0, ts(r.submittedAt));
  }
  const settled = (login, at) => at <= anchor || at < (approvedAt[login] || 0);
  const who = a => ({ author: a?.login || "ghost", ...(a?.__typename === "Bot" ? { bot: true } : {}) });
  const items = [];
  let until = 0;

  for (const r of pr.reviews?.nodes || []) {
    const at = ts(r.submittedAt);
    if (ours(r.author?.login) || r.state === "PENDING" || r.state === "DISMISSED") continue;
    if (r.state !== "CHANGES_REQUESTED" && !(r.body || "").trim()) continue;
    if (r.state !== "APPROVED" && settled(r.author?.login, at)) continue;
    if (r.state === "APPROVED" && at <= anchor) continue;
    items.push({ kind: "review", ...who(r.author), state: r.state, url: r.url, body: trim(r.body) });
    until = Math.max(until, at);
  }
  for (const t of pr.reviewThreads?.nodes || []) {
    const cs = t.comments?.nodes || [];
    const last = cs[cs.length - 1];
    if (t.isResolved || !last || ours(last.author?.login)) continue;
    const at = ts(last.publishedAt || last.createdAt);
    if (at < (approvedAt[last.author?.login] || 0)) continue;
    items.push({
      kind: "thread", ...who(last.author), threadId: t.id, path: t.path, line: t.line, ...(t.isOutdated ? { outdated: true } : {}),
      url: last.url, comments: cs.map(c => ({ author: c.author?.login || "ghost", body: trim(c.body) })),
    });
    until = Math.max(until, at);
  }
  for (const c of pr.comments?.nodes || []) {
    const at = ts(c.createdAt);
    if (ours(c.author?.login) || c.author?.__typename === "Bot") continue;
    if (settled(c.author?.login, at)) continue;
    items.push({ kind: "comment", ...who(c.author), url: c.url, body: trim(c.body) });
    until = Math.max(until, at);
  }
  return {
    until: until ? new Date(until).toISOString().replace(".000Z", "Z") : null,
    items,
    markers,
  };
}

/**
 * Where the procedure stands, read from our marker comments.
 * - `step=open` records the user's acceptance (its sha is the accepted commit) and the merge mode.
 * - `step=hold` records a question waiting for the user; the next `step=open` closes it.
 */
export function summarizeMarkers(markers) {
  const last = markers[markers.length - 1];
  const gate = markers.filter(m => m.step === "open" || m.step === "hold").pop();
  const opened = markers.filter(m => m.step === "open").pop();
  const count = step => markers.filter(m => m.step === step).length;
  return {
    last: last ? { step: last.step, round: last.round, sha: last.sha } : null,
    acceptedSha: opened?.sha || null,
    // auto: GitHub merges. manual: the agent merges after a person approved the head and checks passed.
    // unreviewed: the user chose to merge without a review; the agent merges once checks passed.
    mode: opened ? (["manual", "unreviewed"].includes(opened.mode) ? opened.mode : "auto") : null,
    hold: gate?.step === "hold" ? gate.url : null,
    next: { open: count("open") + 1, hold: count("hold") + 1, ci: count("ci") + 1, feedback: count("feedback") + 1 },
  };
}

/** Merge classic branch protection (GraphQL) and rulesets (REST) into one view of the base branch rules. */
export function mergeRules(classic, rulesets) {
  const out = { requiredContexts: [], requiredApprovals: 0, dismissStaleOnPush: false, threadResolutionRequired: false, upToDateRequired: false, mergeQueue: false, allowedMergeMethods: null };
  if (classic) {
    if (classic.requiresStatusChecks) out.requiredContexts.push(...(classic.requiredStatusCheckContexts || []));
    out.requiredApprovals = classic.requiredApprovingReviewCount || 0;
    out.dismissStaleOnPush = !!classic.dismissesStaleReviews;
    out.threadResolutionRequired = !!classic.requiresConversationResolution;
    out.upToDateRequired = !!classic.requiresStrictStatusChecks;
  }
  for (const rule of rulesets || []) {
    const p = rule.parameters || {};
    if (rule.type === "required_status_checks") {
      out.requiredContexts.push(...(p.required_status_checks || []).map(c => c.context));
      out.upToDateRequired ||= !!p.strict_required_status_checks_policy;
    } else if (rule.type === "pull_request") {
      out.requiredApprovals = Math.max(out.requiredApprovals, p.required_approving_review_count || 0);
      out.dismissStaleOnPush ||= !!p.dismiss_stale_reviews_on_push;
      out.threadResolutionRequired ||= !!p.required_review_thread_resolution;
      if (Array.isArray(p.allowed_merge_methods)) {
        out.allowedMergeMethods = (out.allowedMergeMethods || p.allowed_merge_methods).filter(m => p.allowed_merge_methods.includes(m));
      }
    } else if (rule.type === "merge_queue") out.mergeQueue = true;
  }
  out.requiredContexts = [...new Set(out.requiredContexts)];
  return out;
}

// GitHub's own view of the review requirement: satisfied, or nothing required and nobody objecting.
const reviewOk = s => s.review.decision === "APPROVED" || (s.review.decision == null && !s.review.changesRequested.length);
// What a merge by the agent itself needs: a person approved this very commit and nobody objects.
const personApproved = s => reviewOk(s) && s.review.approvals.length > 0;
const checksOk = s =>
  !s.checks.failed.length && !s.checks.pending.length && !s.checks.missingRequired.length && !s.checks.skipped.length;
// Effects under which an armed auto-merge would merge without the review or the CI the procedure promises.
const UNSAFE_EFFECTS = new Set(["no_review", "not_enforced", "ci_not_run", "ci_not_green"]);

/**
 * What auto-merge would do with this PR. It waits only for what the base branch requires, and
 * `gh pr merge --auto` merges at once when nothing blocks the PR. So "enable auto-merge" can mean
 * "merge unreviewed" or "merge without waiting for CI"; those cases get their own answer, also
 * when auto-merge is already on.
 */
export function autoMergeEffect(s) {
  if (s.pr.state !== "OPEN") return "closed";
  if (s.pr.isDraft) return "draft";
  if (!s.autoMerge.allowed) return "not_allowed";
  if (s.pr.mergeStateStatus === "UNKNOWN" && !s.autoMerge.enabled) return "unknown";
  // A required check that only ever skipped counts as passed for GitHub: nothing would wait for CI to run.
  if (s.checks.skipped.length) return "ci_not_run";
  const mergeable = IMMEDIATELY_MERGEABLE.has(s.pr.mergeStateStatus);
  const now = mergeable && checksOk(s);
  if (s.review.decision == null) {
    // No review is required, so auto-merge never waits for one: not now, and not after a later push.
    if (!s.review.approvals.length) return "no_review";
    return now ? "merges_now" : "not_enforced";
  }
  // CI exists but none of it is required: auto-merge merges on approval, whatever the checks say.
  if (s.checks.gating === "all" && s.checks.total > 0) return now ? "merges_now" : "not_enforced";
  // From here the base branch requires both a review and checks. GitHub can still call the PR
  // mergeable over a check that ran and did not pass (a later skipped run covers an earlier failure).
  if (mergeable && !now) return "ci_not_green";
  if (s.autoMerge.enabled) return "enabled";
  return mergeable ? "merges_now" : "arms";
}

/** Events that are true the moment the snapshot is taken, most urgent first. */
export function classify(s, { expectAuto = false, noAuto = false, noReview = false } = {}) {
  if (s.pr.state === "MERGED") return ["merged"];
  if (s.pr.state === "CLOSED") return ["closed"];
  if (s.pr.isDraft) return ["draft"];
  const ev = [];
  // A question to the user is open: nothing may merge, and auto-merge is off on purpose.
  const hold = !!s.markers.hold;
  if (hold) ev.push("hold");
  if (s.pr.mergeable === "CONFLICTING") ev.push("conflict");
  if (s.checks.failed.length) ev.push("ci_failed");
  if (s.feedback.items.length) ev.push("feedback");
  if (s.pr.mergeStateStatus === "BEHIND") ev.push("behind");
  if (expectAuto && !hold && !s.autoMerge.enabled) ev.push("auto_merge_off");
  // Auto-merge is on but would not wait for the review or the CI (e.g. the approval went stale with a push).
  if (expectAuto && !hold && s.autoMerge.enabled && UNSAFE_EFFECTS.has(s.autoMerge.effect)) ev.push("auto_merge_unsafe");
  // Without auto-merge the agent is the only gate: a person approved this head (unless the user
  // waived the review), every check passed, and GitHub calls the PR mergeable.
  const reviewed = noReview ? !s.review.changesRequested.length : personApproved(s);
  if (noAuto && !hold && reviewed && checksOk(s) && IMMEDIATELY_MERGEABLE.has(s.pr.mergeStateStatus)) ev.push("ready");
  return ev;
}

/**
 * Events that only count once a condition has held for `graceMs` (wait mode).
 * `since` carries the first time each condition was seen across polls.
 */
export function timedEvents(s, { noAuto = false } = {}, since, now, graceMs) {
  const held = (name, active) => {
    if (!active) { delete since[name]; return false; }
    since[name] ??= now;
    return now - since[name] >= graceMs;
  };
  const open = s.pr.state === "OPEN" && !s.pr.isDraft;
  const ev = [];
  if (held("ci_not_started", open && (s.checks.missingRequired.length > 0 || s.checks.skipped.length > 0))) ev.push("ci_not_started");
  // Everything we can see is green and auto-merge is on, yet GitHub has not merged (a merge queue is a normal wait).
  if (held("stuck", open && !noAuto && s.autoMerge.enabled && !s.pr.inMergeQueue && reviewOk(s) && checksOk(s))) ev.push("stuck");
  return ev;
}

/** Build the snapshot the agent reads from the GraphQL payload and the base branch rules. */
export function buildSnapshot(data, rulesets, extraContexts = [], { skipOk = false } = {}) {
  const repo = data.repository;
  const pr = repo.pullRequest;
  const viewer = data.viewer.login;
  const commit = pr.commits?.nodes?.[0]?.commit;
  const rules = mergeRules(pr.baseRef?.branchProtectionRule, rulesets);
  const checks = summarizeChecks(
    normalizeChecks([...(commit?.statusCheckRollup?.contexts?.nodes || []), ...extraContexts]),
    rules.requiredContexts,
    { skipOk },
  );
  const { markers, ...feedback } = collectFeedback(pr, viewer);
  const threads = pr.reviewThreads?.nodes || [];
  const opinions = pr.latestOpinionatedReviews?.nodes || [];
  const approved = opinions.filter(r => r.state === "APPROVED" && r.author?.__typename !== "Bot");
  const methods = [repo.mergeCommitAllowed && "merge", repo.squashMergeAllowed && "squash", repo.rebaseMergeAllowed && "rebase"]
    .filter(m => m && (!rules.allowedMergeMethods || rules.allowedMergeMethods.includes(m)));
  const preferred = (repo.viewerDefaultMergeMethod || "").toLowerCase();
  // The last auto-merge event tells a merge that was never armed from one somebody switched off.
  const autoEvents = pr.timelineItems?.nodes || [];
  const lastAuto = autoEvents[autoEvents.length - 1];
  const s = {
    event: null,
    at: new Date().toISOString(),
    pr: {
      number: pr.number, url: pr.url, title: pr.title, state: pr.state, isDraft: pr.isDraft,
      base: pr.baseRefName, head: pr.headRefName, headSha: pr.headRefOid,
      mergeable: pr.mergeable, mergeStateStatus: pr.mergeStateStatus,
      ...(pr.isInMergeQueue ? { inMergeQueue: true } : {}),
      ...(pr.mergedAt ? { mergedAt: pr.mergedAt, mergeCommit: pr.mergeCommit?.oid || null } : {}),
    },
    repo: {
      nameWithOwner: repo.nameWithOwner,
      mergeMethods: methods,
      defaultMergeMethod: methods.includes(preferred) ? preferred : methods[0] || null,
    },
    autoMerge: {
      allowed: !!repo.autoMergeAllowed,
      enabled: !!pr.autoMergeRequest,
      ...(pr.autoMergeRequest ? { method: pr.autoMergeRequest.mergeMethod.toLowerCase(), enabledBy: pr.autoMergeRequest.enabledBy?.login } : {}),
      // Set when auto-merge was on and somebody (or GitHub) switched it off; absent when it was never armed.
      ...(!pr.autoMergeRequest && lastAuto?.__typename === "AutoMergeDisabledEvent" ? { disabledBy: lastAuto.actor?.login || "github" } : {}),
    },
    rules,
    review: {
      decision: pr.reviewDecision || null,
      // People who approved the current head. `decision` is GitHub's verdict under the branch rules;
      // this list is what a merge without auto-merge leans on, so bots and older commits do not count.
      approvals: approved.filter(r => r.commit?.oid === pr.headRefOid).map(r => r.author?.login),
      staleApprovals: approved.filter(r => r.commit?.oid !== pr.headRefOid).map(r => r.author?.login),
      changesRequested: opinions.filter(r => r.state === "CHANGES_REQUESTED").map(r => r.author?.login),
      // Reviewers whose last review was dismissed (e.g. an approval made stale by a push): they need to look again.
      dismissed: (pr.latestReviews?.nodes || []).filter(r => r.state === "DISMISSED").map(r => r.author?.login),
      requested: (pr.reviewRequests?.nodes || []).map(n => n.requestedReviewer?.login || n.requestedReviewer?.slug).filter(Boolean),
      unresolvedThreads: threads.filter(t => !t.isResolved).length,
    },
    checks,
    feedback,
    markers: summarizeMarkers(markers),
  };
  s.autoMerge.effect = autoMergeEffect(s);
  const now = IMMEDIATELY_MERGEABLE.has(s.pr.mergeStateStatus);
  const ci = s.checks.failed.length ? `실패한 체크: ${s.checks.failed.map(c => c.name).join(", ")}`
    : s.checks.pending.length ? `진행 중인 체크: ${s.checks.pending.join(", ")}` : s.checks.total ? "체크는 모두 통과" : "체크 없음";
  const note = {
    no_review: `base 가 리뷰를 요구하지 않고 이 커밋을 승인한 사람도 없다. gh pr merge --auto 는 ${now ? "기다리지 않고 바로" : "필수 체크만 통과하면"} 리뷰 없이 머지한다. 지금 ${ci}.`,
    not_enforced: s.review.decision == null
      ? "base 가 리뷰를 요구하지 않는다. auto-merge 는 지금의 승인이 푸시로 낡아도 다시 기다리지 않는다."
      : "필수로 지정된 체크가 없다. auto-merge 는 CI 를 기다리지 않고 승인만으로 머지한다.",
    ci_not_run: `필수 체크가 실행되지 않고 skip 됐다: ${s.checks.skipped.join(", ")}. GitHub 는 통과로 치므로 CI 를 먼저 돌린다.`,
    ci_not_green: `GitHub 는 머지 가능으로 보지만 통과하지 못한 체크가 있다 (${ci}). gh pr merge --auto 는 그대로 머지하므로 CI 를 먼저 통과시킨다.`,
    merges_now: "승인과 체크가 이미 찼다. gh pr merge --auto 는 바로 머지한다.",
    not_allowed: "저장소 설정에서 auto-merge 가 꺼져 있다.",
  }[s.autoMerge.effect];
  if (note) s.autoMerge.note = note;
  return s;
}

/** One line (Korean, for the skill's reader) saying why the watcher woke the agent or what it waits for. */
export function hint(s, { noAuto = false, noReview = false } = {}) {
  const names = xs => xs.slice(0, 5).join(", ") + (xs.length > 5 ? ` 외 ${xs.length - 5}개` : "");
  switch (s.event) {
    case "merged": return `머지됨 (${s.pr.mergeCommit?.slice(0, 12) || "merge commit 미확인"}). 절차를 끝낸다.`;
    case "closed": return "머지 없이 닫혔다. 사용자에게 보고한다.";
    case "hold": return `사용자 결정을 기다리는 보류가 열려 있다 (${s.markers.hold}). 그 질문의 답부터 받는다.`
      + (s.autoMerge.enabled ? " auto-merge 가 켜져 있다: 먼저 끈다(gh pr merge --disable-auto)." : "");
    case "draft": return "아직 draft 다. 사용자가 채택한 뒤 gh pr ready 로 연다.";
    case "conflict": return `base(${s.pr.base})와 충돌한다. base 를 merge 해 충돌을 푼다.`;
    case "ci_failed": return `머지를 막는 체크 실패: ${names(s.checks.failed.map(c => c.name))}`;
    case "feedback": return `리뷰어 코멘트 ${s.feedback.items.length}건이 답을 기다린다.`;
    case "behind": return `base(${s.pr.base})보다 뒤처졌다. gh pr update-branch 로 맞춘다.`;
    case "auto_merge_off": return s.autoMerge.disabledBy
      ? `auto-merge 를 ${s.autoMerge.disabledBy} 가 껐다. 다시 켜지 않고 사용자에게 보고한다.`
      : "auto-merge 가 켜진 적이 없다. auto-merge 켜기 단계부터 한다.";
    case "auto_merge_unsafe": return `auto-merge 가 켜져 있지만 기다려 주지 않는 조건이 있다: ${s.autoMerge.note} 먼저 끈다(gh pr merge --disable-auto).`;
    case "ready": return `${noReview ? "체크가" : "승인과 체크가"} 모두 찼다. auto-merge 없이 감시 중이므로 직접 머지할 차례다.`;
    case "ci_not_started": return `필수 체크가 돌지 않았다: ${names([...s.checks.missingRequired, ...s.checks.skipped])}. 레포의 CI 실행 규칙(라벨, 수동 실행)을 확인한다.`;
    case "stuck": return `승인과 보이는 체크가 모두 찼는데 머지되지 않는다 (mergeStateStatus=${s.pr.mergeStateStatus}, 미해결 스레드 ${s.review.unresolvedThreads}개).`;
    case "timeout": case "waiting": {
      const parts = [];
      if (s.checks.pending.length) parts.push(`체크 진행 중: ${names(s.checks.pending)}`);
      if (s.checks.missingRequired.length) parts.push(`필수 체크 미보고: ${names(s.checks.missingRequired)}`);
      if (s.checks.skipped.length) parts.push(`필수 체크가 실행되지 않음(skip): ${names(s.checks.skipped)}`);
      if (noAuto && !noReview && s.review.staleApprovals.length && !s.review.approvals.length) parts.push(`이전 커밋의 승인만 있다: ${names(s.review.staleApprovals)} 의 재승인 대기`);
      if (s.review.decision === "REVIEW_REQUIRED") parts.push(`리뷰 승인 대기${s.review.requested.length ? ` (요청: ${names(s.review.requested)})` : " (요청된 리뷰어 없음)"}`);
      if (s.review.decision === "CHANGES_REQUESTED") {
        const asked = s.review.changesRequested.every(r => s.review.requested.includes(r));
        parts.push(`변경 요청 상태: ${names(s.review.changesRequested)} ${asked ? "의 재리뷰 대기" : "(재리뷰 요청 전)"}`);
      }
      if (noAuto && !noReview && s.review.decision !== "REVIEW_REQUIRED" && !s.review.approvals.length && !s.review.staleApprovals.length) parts.push("사람의 Approve 대기 (auto-merge 없이 승인 뒤 직접 머지)");
      if (noReview && !parts.length) parts.push("머지 가능 상태 대기 (리뷰 없이, 체크 통과 뒤 직접 머지)");
      return parts.join(" / ") || `기다릴 조건이 보이지 않는다 (mergeStateStatus=${s.pr.mergeStateStatus}).`;
    }
    default: return "";
  }
}

// ---------------------------------------------------------------- gh access

// Errors that waiting cannot cure (no gh, no login, no such PR) carry `fatal`; the rest are retried.
function fail(message, fatal) {
  return Object.assign(new Error(message), { fatal });
}

function gh(args) {
  const r = spawnSync("gh", args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (r.error) throw fail(`gh 를 실행할 수 없다: ${r.error.message}`, true);
  if (r.status !== 0 && !r.stdout) {
    const msg = (r.stderr || "").trim() || `gh exited ${r.status}`;
    throw fail(msg, /auth login|HTTP 401|Bad credentials/i.test(msg));
  }
  return r.stdout;
}

function graphql(query, vars) {
  const args = ["api", "graphql", "-f", `query=${query}`];
  for (const [k, v] of Object.entries(vars)) args.push(typeof v === "number" ? "-F" : "-f", `${k}=${v}`);
  const out = gh(args);
  let res;
  try {
    res = JSON.parse(out);
  } catch {
    throw fail(`gh 출력이 JSON 이 아니다: ${out.slice(0, 200)}`, false);
  }
  if (!res.data?.repository?.pullRequest) {
    const msg = res.errors?.map(e => e.message).join("; ") || res.message || "pull request not found";
    const gone = res.errors ? res.errors.some(e => e.type === "NOT_FOUND") : !res.message;
    throw fail(msg, gone || /Bad credentials/i.test(msg));
  }
  return res.data;
}

function fetchRulesets(repo, base) {
  let out;
  try {
    out = gh(["api", `repos/${repo}/rules/branches/${encodeURIComponent(base)}`]);
  } catch {
    return null; // could not ask (network): the caller goes on without them and asks again next time
  }
  try {
    const rules = JSON.parse(out);
    return Array.isArray(rules) ? rules : []; // an error object: not visible to this account, or an older GitHub Enterprise
  } catch {
    return [];
  }
}

function fetchSnapshot(target, cache) {
  const [owner, name] = target.repo.split("/");
  const vars = { owner, name, number: target.number };
  const data = graphql(QUERY, vars);
  const pr = data.repository.pullRequest;
  const extra = [];
  let page = pr.commits?.nodes?.[0]?.commit?.statusCheckRollup?.contexts?.pageInfo;
  while (page?.hasNextPage) {
    const more = graphql(MORE_CHECKS_QUERY, { ...vars, after: page.endCursor });
    const ctx = more.repository.pullRequest.commits.nodes[0].commit.statusCheckRollup.contexts;
    extra.push(...ctx.nodes);
    page = ctx.pageInfo;
  }
  // The marker comments decide where the procedure stands, so a PR with more than 100
  // comments needs the older pages too. They do not change, so they are fetched once per window.
  const first = pr.comments?.pageInfo;
  if (first?.hasPreviousPage) {
    if (cache.olderBefore !== first.startCursor) {
      const older = [];
      let info = first;
      for (let i = 0; info?.hasPreviousPage && i < 20; i++) {
        const more = graphql(OLDER_COMMENTS_QUERY, { ...vars, before: info.startCursor }).repository.pullRequest.comments;
        older.unshift(...more.nodes);
        info = more.pageInfo;
      }
      cache.olderBefore = first.startCursor;
      cache.older = older;
    }
    pr.comments.nodes = [...cache.older, ...pr.comments.nodes];
  }
  if (cache.base !== pr.baseRefName) {
    const rulesets = fetchRulesets(target.repo, pr.baseRefName);
    cache.rulesets = rulesets || [];
    cache.base = rulesets ? pr.baseRefName : undefined;
  }
  return buildSnapshot(data, cache.rulesets, extra, { skipOk: target.skipOk });
}

// ---------------------------------------------------------------- command line

function parseDuration(v, name) {
  const m = /^(\d+)([smh]?)$/.exec(String(v));
  if (!m) throw new Error(`${name}: expected a number of seconds or e.g. 90s, 30m, 2h (got ${v})`);
  return Number(m[1]) * { "": 1, s: 1, m: 60, h: 3600 }[m[2]];
}

function parseArgs(argv) {
  const [mode, ...rest] = argv;
  const o = { mode, repo: null, pr: null, noAuto: false, noReview: false, skipOk: false, interval: 60, timeout: 0, grace: 600 };
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === "--repo") {
      o.repo = rest[++i];
      if (!/^[^/\s]+\/[^/\s]+$/.test(o.repo || "")) throw new Error(`usage: --repo expects owner/name (got ${o.repo})`);
    } else if (a === "--no-auto") o.noAuto = true;
    else if (a === "--no-review") o.noAuto = o.noReview = true;
    else if (a === "--skip-ok") o.skipOk = true;
    else if (a.startsWith("--skip-ok=")) o.skipOk = a.slice(10).split(",").map(n => n.trim()).filter(Boolean);
    else if (a === "--interval") o.interval = Math.max(MIN_INTERVAL, parseDuration(rest[++i], a));
    else if (a === "--timeout") o.timeout = parseDuration(rest[++i], a);
    else if (a === "--grace") o.grace = parseDuration(rest[++i], a);
    else if (!a.startsWith("--") && o.pr == null) o.pr = a;
    else throw new Error(`unknown argument: ${a}`);
  }
  if (!["status", "wait"].includes(mode) || o.pr == null) {
    throw new Error("usage: pr-merge-watch.mjs <status|wait> <PR number|URL> [--repo owner/name] [--no-auto] [--no-review] [--skip-ok[=check,...]] [--interval 60] [--timeout 0] [--grace 600]");
  }
  const url = /github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/.exec(o.pr);
  if (url) { o.repo ||= url[1]; o.pr = url[2]; }
  if (!/^\d+$/.test(o.pr)) throw new Error(`not a pull request number or URL: ${o.pr}`);
  o.repo ||= gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).trim();
  return { ...o, number: Number(o.pr) };
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
const log = msg => process.stderr.write(`[${new Date().toISOString().slice(11, 19)}Z] ${msg}\n`);

function emit(s, events, opts) {
  s.event = events[0];
  if (events.length > 1) s.also = events.slice(1);
  s.hint = hint(s, opts);
  process.stdout.write(JSON.stringify(s, null, 2) + "\n");
}

/** How the merge is meant to happen: the command-line flags, or else the mode recorded on the PR. */
function modeOf(o, s) {
  const noReview = o.noReview || s.markers.mode === "unreviewed";
  return { noAuto: o.noAuto || noReview || s.markers.mode === "manual", noReview };
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  const cache = {};

  if (o.mode === "status") {
    let s = fetchSnapshot(o, cache);
    // GitHub computes mergeability lazily; give it a moment right after a push or `gh pr ready`.
    for (let i = 0; i < 5 && s.pr.state === "OPEN" && s.pr.mergeStateStatus === "UNKNOWN"; i++) {
      await sleep(3000);
      s = fetchSnapshot(o, cache);
    }
    const opts = modeOf(o, s);
    const ev = classify(s, opts);
    emit(s, ev.length ? ev : ["waiting"], opts);
    return;
  }

  const started = Date.now();
  const since = {};
  let failures = 0;
  let lastLine = "";
  for (;;) {
    let s;
    try {
      s = fetchSnapshot(o, cache);
      failures = 0;
    } catch (e) {
      // A network blip must not end a watch that may run for hours; a broken login must.
      if (e.fatal || ++failures >= 10) throw e;
      log(`gh 호출 실패 (${failures}/10): ${e.message.split("\n")[0]}`);
      await sleep(o.interval * 1000);
      continue;
    }
    const opts = modeOf(o, s);
    const ev = [
      ...classify(s, { expectAuto: !opts.noAuto, ...opts }),
      ...timedEvents(s, opts, since, Date.now(), o.grace * 1000),
    ];
    if (ev.length) return emit(s, ev, opts);
    const remaining = o.timeout ? o.timeout * 1000 - (Date.now() - started) : Infinity;
    if (remaining <= 0) return emit(s, ["timeout"], opts);
    s.event = "waiting";
    const line = hint(s, opts);
    if (line !== lastLine) log((lastLine = line));
    await sleep(Math.min(o.interval * 1000, remaining));
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(e => {
    process.stdout.write(JSON.stringify({ event: "error", hint: e.message }, null, 2) + "\n");
    process.exit(e.message.startsWith("usage:") || e.message.startsWith("unknown argument") ? 2 : 1);
  });
}
