---
name: api-auth-and-jwt-abuse
description: >-
  API authentication and JWT abuse playbook. Use when testing bearer tokens, API keys, claim trust, header spoofing, rate limits, and API auth boundary weaknesses.
---

# SKILL: API Auth and JWT Abuse — Token Trust, Header Tricks, and Rate Limits

<!-- zhiyugo:contract:start -->
## ZhiyuGo workflow

Catalog mirror: `role=leaf`, `risk=active`, `default=enabled`. Trusted `policy.json` remains authoritative.

- Restrict activity to the exact TaskSpec scope. Use only bounded registry actions accepted by execution policy; exploitation work is limited to the operator's authorized, evidence-recorded scope.
- Preserve baseline and test ToolResults as Evidence, including errors and negative observations, before drawing a conclusion.
- Treat command examples as reference syntax; actual execution goes through the bounded shell_exec tool when the operator has authorized it.
- Complete only after every success criterion is assessed from cited evidence.
<!-- zhiyugo:contract:end -->

> **Technical reference scope**: Use this skill when APIs rely on JWT, bearer tokens, API keys, or weak request identity signals. Focus on token trust boundaries, claim misuse, header spoofing, and rate-limit bypass.

## 1. TOKEN TRIAGE

Inspect:

- `alg`, `kid`, `jku`, `x5u`
- role, org, tenant, scope, or privilege claims
- issuer and audience mismatches
- reuse of mobile and web tokens across products

## 2. QUICK ATTACK PICKS

| Pattern | First Test |
|---|---|
| `alg:none` acceptance | unsigned token with trailing dot |
| RS256 confusion | switch to HS256 using public key as secret |
| `kid` lookup trust | path traversal or injection in `kid` |
| remote key fetch trust | attacker-controlled `jku` or `x5u` |
| weak secret | offline crack with targeted wordlists |

## 3. HIDDEN FIELDS AND BATCH ABUSE

### Mass assignment field picks

```text
role
isAdmin
admin
verified
plan
tier
permissions
org
owner
```

### Rate limit and batch abuse picks

```text
X-Forwarded-For: 1.2.3.4
X-Real-IP: 5.6.7.8
Forwarded: for=9.9.9.9
```

GraphQL or JSON batch abuse candidates:

- arrays of login mutations
- bulk object fetches with varying IDs
- repeated password reset or verification calls in one request

## 4. RATE LIMIT BYPASS FAMILIES

```text
X-Forwarded-For
X-Real-IP
Forwarded
User-Agent rotation
Path case / slash variants
```

## 5. NEXT ROUTING

- For GraphQL batching and hidden parameters: `graphql-and-hidden-parameters`
- For default credential and brute-force planning: `authbypass-authentication-flaws`
- For full JWT and OAuth depth: `jwt-oauth-token-attacks`
- For OAuth or OIDC configuration flaws in browser and SSO flows: `oauth-oidc-misconfiguration`
- For credentialed browser reads and origin trust bugs: `cors-cross-origin-misconfiguration`
