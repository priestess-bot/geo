# Browser Capture Worker

This isolated worker consumes only `browser.capture` and `browser.egress_test`
Durable Jobs. It resolves
approved `browser_egress.*` Secret Store versions in memory, uses one sticky
proxy lease for pre/target/post requests, encrypts the resulting Page Bundle,
and commits one fenced Workflow C observation.
