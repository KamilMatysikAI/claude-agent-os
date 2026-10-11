---
id: A-003
project: kawiarnia-subskrypcja
title: "Płatności cykliczne: odnowienie co 14 dni i karta zapasowa"
owner: soft
type: task
status: in_progress
priority: high
due: 2026-10-15
created: 2026-10-03
closed:
size: medium
autonomy: full
source: local
profile:
blocked_by: []
unblocked_by:
decision:
evidence:
lock:
---

# Płatności cykliczne: odnowienie co 14 dni i karta zapasowa

## Goal

Abonament odnawia się sam co 14 dni. Gdy karta odmówi, system próbuje ponownie po 24 h, a klient dostaje maila z linkiem do zmiany karty. Zero ręcznego pilnowania płatności.

## Definition of done

- Odnowienie co 14 dni działa na koncie testowym operatora płatności (3 cykle przyspieszone).
- Odmowa karty: ponowna próba po 24 h i mail z linkiem do zmiany karty.
- Po 2 nieudanych próbach abonament przechodzi w pauzę, nie w anulowanie.
- Testy zielone, log z 3 cykli w `materials/test-platnosci.md`.

## Owner notes

## Progress log

- 2026-10-03 09:00 - Zadanie utworzone przez ceo.
- 2026-10-09 09:40 - Konto testowe operatora płatności podłączone, webhook odnowienia odbiera zdarzenia.
- 2026-10-10 14:15 - Cykl 14 dni działa na przyspieszonym zegarze: 3 odnowienia, 3 faktury.
- 2026-10-11 08:20 - Odmowa karty: ponowna próba po 24 h gotowa, w toku mail z linkiem do zmiany karty.
