Yes, a breakout strategy fits as a sampler. Its rules decide which moments get examined at all, and everything downstream (labels, weights, features, meta-model, backtest) runs unchanged on its output.

**How a breakout strategy would map onto the system:**
- **Sampler:** fires when price leaves a defined range, e.g. the Asian-session high/low or the last N hours. `t0` is the close of the bar that broke out, and `direction` is the side it broke (+1 above, −1 below).
- **Side rule:** `follow` trades the breakout. `fade` bets it's a false breakout and trades the reversal. Same events, two strategies, compared head to head.
- **Code:** a `BreakoutEventsConfig` holding the rule's parameters (range definition, buffer, session times), a detect function that returns the events table, and one line registering it beside CUSUM. Its events land under their own `config=<hash>` folder.

**Where to put rule details:** very specific rules can work against you, because each one cuts the event count, and the meta-model needs volume. For reference, CUSUM's ~1.9 events a day gives about 2,400 events over five years of one pair, roughly the minimum for a tree model with purged CV. A strategy firing twice a week won't give enough to learn from without many more years or pairs. A useful split:
- **In the sampler:** what defines the setup ("price closed outside the Asian range").
- **In features:** what might make one instance good or bad (how wide the range was, how fast the break happened, the spread, time of day, recent vol).

Then the meta-model *learns* which breakouts work, instead of you hard-coding filters you'd otherwise have to tune by hand. Every hand-tuned filter also counts as another trial against the multiple-testing guard in §9.4.

**One thing to fix before a second sampler exists:** the events table currently has three CUSUM-specific columns (`ret`, `z`, `vol`). A breakout sampler would want different ones (range high/low, distance past the range). Before adding it, I'd split the schema into core columns every sampler must produce (`event_id`, `symbol`, `t0`, `direction`, `price_t0`) and sampler-specific extras that downstream stages ignore. It's a small change, best made when the second sampler arrives.

**On "events":** yes. "Event" should mean only a sampler's output: a row in the `events` table. The code uses it that way now (`event_id`, `build_events`, `EventsMeta`). The ambiguity risk is in the later stages, which also have things that "happen". I'd keep these words distinct:

| term | meaning | stage |
|---|---|---|
| **event** | a moment a sampler flagged: `t0` + `direction` | sampler |
| **fire** | the sampler's trigger itself ("CUSUM fired up") | sampler |
| **side** | long/short after the side rule; an event has a direction, not a side | side rule |
| **touch** | price hitting a barrier (upper, lower, vertical) | labels |
| **outcome** | what the label records: `pt`, `sl`, `timeout`, `insufficient_data` | labels |
| **exit** | when a position closes (`t1` for labels; the exit policy in the backtest) | labels / exits |
| **trade** | an event acted on in the backtest: side + size + entry + exit, after costs | backtest |
| **strategy** | sampler + side rule, named by `strategy_id` (e.g. `cusum_h3_follow`) | — |

The distinction that matters most is event vs trade. Not every event becomes a trade (the meta-model and sizing filter them), and a trade has costs and a size where an event has neither.

Want me to add this table to the pipeline spec as a glossary section? I'd do it in the same update as the inventory changes.