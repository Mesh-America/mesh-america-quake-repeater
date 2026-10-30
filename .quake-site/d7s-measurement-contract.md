# D7S measurement and event contract

Verified 2026-10-02 against Omron product specification 9915815-2A2, supplied in [RAK's D7S repository](https://github.com/RAKWireless/RAK12027-D7S/tree/main/datasheet). Pages below use the printed page numbers. The checked PDF SHA-256 is `CC90F8943669353FF173A5B82A079AD01993A26D6EB194681720645A4AF6F19D`.

## Measurements

All measurement words are unsigned 16-bit, most significant byte first.

| Measurement | Register | Interpretation | Evidence |
|---|---|---|---|
| Live SI | 0x2000–0x2001 | raw / 10 cm/s (kine); raw / 1000 m/s | Page 18 specifies one decimal place; physical unit follows stored SI and RAK's matching conversion. |
| Live PGA | 0x2002–0x2003 | Keep raw until clarified | Page 18 says integer and omits the unit; RAK converts it as raw / 1000 m/s². These are not sufficient to settle the discrepancy. |
| Stored SI | Record offset 0x08–0x09 | raw / 10 cm/s (kine); raw / 1000 m/s | Pages 20 and 22 explicitly specify one decimal place and kine. |
| Stored PGA | Record offset 0x0A–0x0B | raw / 10 cm/s² (gal); raw / 1000 m/s²; raw / 9806.65 g | Pages 20 and 22 explicitly specify one decimal place and gal. g uses standard gravity 9.80665 m/s². |

Latest records start at 0x3000 through 0x3400; ranked records at 0x3500 through 0x3900, with a 0x100 stride. Ranking is by SI, not PGA. A stored record may predate boot and must not automatically be presented as a new event.

For the user's observed SI raw 433, the SI interpretation is 43.3 cm/s. **Their PGA raw 1481 was a live reading:** do not claim a confirmed conversion for it. A *stored* PGA raw 1481 would mean 148.1 gal, 1.481 m/s², approximately 0.151 g.

SI describes the shaking's potential effect on structures; PGA describes the strongest measured acceleration. Neither gives earthquake magnitude, an epicenter, or a damage determination. Moving an enclosure is not a calibrated ground-motion measurement.

## Event flags

EVENT at 0x1002 is read-to-clear (page 17). Software must preserve its flags for consumers. A failed read may already have cleared them; retain the driver's uncertainty indication.

| Bit / mask | Suggested app label | Meaning |
|---|---|---|
| 0 / 0x01 | Significant shaking detected | Earthquake shutoff signal was asserted. This is the manufacturer's threshold decision, not a Richter magnitude. |
| 1 / 0x02 | Tilt detected | Collapse/tilt shutoff signal was asserted. This does not establish that a building collapsed. |
| 2 / 0x04 | Sensor self-test error | Self-diagnostic error was reported. |
| 3 / 0x08 | Sensor baseline error | Offset acquisition error was reported. |
| 7 / 0x80 | EVENT read possibly lost flags | Not a device flag: firmware marker that an EVENT read failed and may have cleared flags that were never seen. |

A latched mask is not an event count. A zero mask means no retained flags, not proof a self-test ran successfully. Telemetry retains observed flags since the first successful poll. INT1/INT2 remain supported but are excluded from normal app display.

The default H shutoff threshold is described as equivalent to JMA seismic intensity 5 Upper or higher (page 18). This is neither Richter 5 nor a precise measured intensity value. Do not invent SI-to-magnitude bands from it.

## Processing and alerts

State 0 is standby; state 1 is normal mode outside standby, primarily earthquake processing; states 2, 3 and 4 are installation, offset acquisition and self-test. State 1 alone does not establish an earthquake.

The specification describes SI/PGA calculation every 320 ms over a two-minute processing window, followed by storage; continued motion can cause another window (page 8). Live values return to zero after processing. Capture a newly completed stored record for final physical-unit reporting, and distinguish it from pre-existing history. INT2 also indicates calibration and self-test, so it must not be the sole trigger for an earthquake message.

Keep existing generic telemetry in raw counts until the app-facing contract explicitly identifies units and live versus stored readings. Completed alerts can use confirmed stored SI/PGA conversions without waiting for live-PGA clarification. Human severity categories still require a separately justified model.

## Remaining vendor question

In Omron specification 9915815-2A2, page 18 describes live PGA at 0x2002–0x2003 as an integer with no unit, while pages 20/22 specify stored PGA as 0.1 gal per count. RAK's `getInstantaneusPGA()` divides live raw PGA by 1000 and labels the result m/s². Is live PGA also 0.1 gal per count on D7S-A0001, or does it use another scale? Please provide the corrected register definition or erratum.

Reference implementation: [RAK D7S source](https://github.com/RAKWireless/RAK12027-D7S/blob/000a5b12d86eea3fbae0e600e92fe53d75d82784/src/RAK12027_D7S.cpp). Its conversions corroborate stored scaling but do not override the manufacturer's live-register ambiguity.
