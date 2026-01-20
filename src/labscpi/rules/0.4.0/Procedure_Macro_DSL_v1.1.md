# Procedure Macro DSL v1.1 (for Hardware Test Procedures)

> **Status note (2025-12-31):** This document is deprecated. Its content is now integrated into `test_rules_llm_ready.md` as the canonical macro grammar and should not be maintained separately.

This document defines a compile-time macro layer for hardware test procedures.
It allows authors to use tables, loops, and conditionals while preserving determinism
and stable measurement IDs.

---

## 1. Definitions

### 1.1 Authored procedure
A test procedure written by a human. It may contain:
- normal action lines
- macro directive lines beginning with `@`

### 1.2 Expanded procedure
A linear list of steps with:
- no macro directives
- concrete numeric measurement IDs `{n}`

### 1.3 Compile-time determinism
All macro constructs must be evaluable without running the test.

Allowed compile-time inputs:
- constants from `@LET`
- loop indices
- table rows
- `COUNT(<table>)`

Forbidden:
- runtime measurements
- operator input
- external state

---

## 2. Directive syntax

Directive lines start with `@` and may appear only inside:
- Test steps
- Success conditions

---

## 3. Directives

### 3.1 @LET
Define a compile-time variable.

Syntax:
@LET NAME = EXPR

---

### 3.2 @TABLE / @ROW / @ENDTABLE

Syntax:
@TABLE NAME
@ROW NAME key=value key=value
@ENDTABLE

Example:
@TABLE C2
@ROW C2 io=IO#DSC68 sig=I#C2_0 pin="P10 pin 4"
@ENDTABLE

---

### 3.3 COUNT(TABLE)
Returns number of rows in TABLE.

---

### 3.4 @ALLOC

Auto allocation:
@ALLOC BASE = COUNT(TABLE)

Manual allocation:
@ALLOC BASE START=100 COUNT=COUNT(TABLE)

---

### 3.5 @FOR

Table loop:
@FOR i, row IN TABLE
...
@ENDFOR

Range loop:
@FOR i IN 0..N
...
@ENDFOR

---

### 3.6 @IF / @ELSE / @ENDIF

Compile-time conditional.

---

## 4. Expressions

Supported:
- + - * / %
- comparisons
- boolean AND OR NOT

---

## 5. Measurement IDs

Allowed contexts:
- as {ID_EXPR}
- {ID_EXPR} at start of expected line

ID_EXPR must resolve to a non-negative integer (0 allowed).

---

## 6. Macro substitution

Use ${...} for macro substitution.

---

## 7. Expansion semantics

Macros expand in authored order.
Expanded procedure must be deterministic.

---

## 8. Validation rules

The compiler must reject:
- unknown variables
- non-deterministic loops
- overlapping ID allocations
- duplicate IDs
- orphan expected IDs

---

## 9. JSON handling

JSON may contain macro directives.
Expanded JSON is optional but recommended.

---

## 10. Code generation guidance

- Parse macros
- Validate
- Generate efficient loops
- Log expanded IDs at runtime

---

## 11. Examples

See documentation body for worked examples.

---

## 12. Summary

This DSL enables maintainable test authoring while preserving auditability and determinism.
