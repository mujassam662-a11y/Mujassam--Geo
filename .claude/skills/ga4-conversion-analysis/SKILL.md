---
name: ga4-conversion-analysis
description: Analyse GA4 traffic, acquisition, devices, engagement and conversion events after verifying the real event configuration.
---

# ga4-conversion-analysis

## Procedure
1. `GA4Connector.event_inventory()` + list `eventName` values from the events report.
2. Ask the owner to map events to funnel steps (upload, quote, checkout, payment). Do not infer from names.
3. Confirmed orders and revenue come from the order export, reconciled with GA4 purchase events if present.
4. Report: sessions/engaged sessions by landing page, source/medium, device, region; conversion rates only for mapped events.

## Output
`{window, landing_pages:[...], acquisition:[...], devices:[...], funnel:[{step, event, count, rate, measurable}], caveats:[...]}`
