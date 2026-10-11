---
id:
project:
title: Sprawdź daty wygaśnięcia wszystkich domen firmowych
owner: research
type: task
status: todo
priority: normal
due: 2026-10-16
created: 2026-10-10
closed:
size: small
autonomy: full
source: panel
profile:
blocked_by: []
unblocked_by:
decision:
evidence:
lock:
---

# Sprawdź daty wygaśnięcia wszystkich domen firmowych

## Goal

Jedna tabela z każdą domeną firmy, rejestratorem i datą wygaśnięcia, żeby żadna nie wygasła przez przypadek.

## Context

Zgłoszone z panelu przez Olę: „Sprawdź, kiedy wygasają nasze domeny, chyba jedna jest blisko”.
Lista domen jest w `.claude/rules/context.md`, sekcja „Tools and accounts”. Tylko publiczne zapytania WHOIS/RDAP, bez logowania do rejestratorów.

## Steps

- [ ] Odczytać listę domen z context.md
- [ ] Sprawdzić datę wygaśnięcia każdej domeny przez publiczne RDAP
- [ ] Tabela posortowana po dacie, oznaczyć wszystko, co wygasa w ciągu 60 dni
- [ ] Dla każdej oznaczonej domeny założyć zadanie dla Oli „odnów domenę X” z linkiem do rejestratora jako pierwszym krokiem

## Definition of done

Tabela w `inbox/done/wygasniecie-domen-RRRR-MM-DD.md`; zadania dla Oli założone dla domen wygasających w ciągu 60 dni.

## Owner notes

## Progress log
