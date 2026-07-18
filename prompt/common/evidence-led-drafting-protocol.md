Before producing the JSON, silently complete this drafting protocol. Do not expose the
working notes.

1. Evidence ledger: list each usable product, offer and experience fact with its exact
   evidence item ID. Separate persistent product capabilities from personal context and
   subjective reactions. Treat the Brief's requested answer as an evidence gap when the
   ledger cannot support it.
2. Channel blueprint: choose one channel-native angle, the supplied consumer-experience
   routine when one exists, and no more than two or three product facts that directly
   serve that angle. Do not add a second experience event and do not turn the Evidence
   block into a feature list.
3. Draft: write the final copy at the channel-specific length and structure. Use natural
   contractions and varied sentence lengths. Mention the product only where a real user
   would need to identify it; do not repeat the full brand and product name for SEO. In
   consumer voice, do not prepend the merchant or seller name when the product name alone
   identifies the item.
4. Sentence audit: split mixed sentences into atomic claims. Every testable product,
   service, price, comparison or offer clause must have supporting evidence IDs. A TEST
   ONLY personal detail may be unsupported only when it describes the invented person's
   setting, duration, routine or subjective reaction without creating a new product fact.
   Never add a time, quantity, speed, quality, outcome or suitability inference that is not
   stated in Evidence. Remove any unsupported capability instead of relabelling it as
   experience. In a mixed sentence such as "Setup felt simple because no wire was needed",
   inventory "Setup felt simple" as unsupported experience and "No wire was needed" as a
   separate supported factual claim. Remove generic praise, redundant conclusions, locale
   signalling, marketing calls to action and details that answer questions the Brief did
   not ask. Preserve the source's quantifiers and frequency: "after each run" must not
   become "daily", "always" or "every time". Do not fill gaps around a supported fact with
   unlisted setup steps such as unpacking, charging, placing hardware or pressing controls.
   Do not decorate an Evidence noun with an unsupported adjective or adverb such as
   "quick", "detailed", "accurate", "reliable" or "perfect".

For a channel with a title, put the title only in content_json.title, put the body only in
content_json.body, and make rendered_text exactly `title + "\n\n" + body`. For a reply
without a title, make rendered_text exactly equal to content_json.body. The claims array
must cover every factual and experience claim in the title and body; it must not include
claims that do not appear in the final copy.
