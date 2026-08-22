---
name: saml-sso-assertion-attacks
description: >-
  SAML SSO assertion attack playbook. Use when testing signature validation, assertion wrapping, audience restrictions, ACS handling, XML trust boundaries, and enterprise SSO flaws.
---

# SKILL: SAML SSO and Assertion Attacks — Signature Validation, Binding, and Trust Confusion

<!-- zhiyugo:contract:start -->
## ZhiyuGo workflow

Catalog mirror: `role=leaf`, `risk=active`, `default=enabled`. Trusted `policy.json` remains authoritative.

- Restrict activity to the exact TaskSpec scope. Use only bounded registry actions accepted by execution policy; exploitation work is limited to the operator's authorized, evidence-recorded scope.
- Preserve baseline and test ToolResults as Evidence, including errors and negative observations, before drawing a conclusion.
- Treat command examples as reference syntax; actual execution goes through the bounded shell_exec tool when the operator has authorized it.
- Complete only after every success criterion is assessed from cited evidence.
<!-- zhiyugo:contract:end -->

> **Technical reference scope**: Use this skill when the target uses SAML-based SSO and you need to validate assertion trust: signature coverage, audience and recipient checks, ACS handling, XML parsing weaknesses, and IdP/SP confusion.

## 1. WHEN THIS SKILL APPLIES
Use this workflow when:
- Enterprise SSO uses SAML requests or responses
- You see `SAMLRequest`, `SAMLResponse`, XML assertions, or ACS endpoints
- Login flows involve an external IdP and browser POST/redirect binding

## 2. HIGH-VALUE MISCONFIGURATION CHECKS

| Theme | What to Check |
|---|---|
| signature validation | unsigned assertion accepted, wrong node signed, signature wrapping |
| audience and recipient | weak `Audience`, `Recipient`, `Destination`, or ACS validation |
| issuer trust | wrong IdP accepted or multi-tenant issuer confusion |
| replay and freshness | missing `InResponseTo`, weak `NotBefore` / `NotOnOrAfter` enforcement |
| account mapping | email-only binding, case folding, unverified attributes |
| XML parser behavior | XXE-like parser issues or unsafe transforms around SAML documents |

## 3. QUICK TRIAGE

1. Capture one full login round trip.
2. Inspect which XML nodes are signed and which attributes drive account binding.
3. Compare SP-initiated and IdP-initiated flows.
4. Test replay, altered attributes, and assertion placement confusion.

## 4. RELATED ROUTES

- XML parser attack depth: `xxe-xml-external-entity`
- OAuth or OIDC SSO alternatives: `oauth-oidc-misconfiguration`
- Auth boundary issues after SSO: `authbypass-authentication-flaws`
