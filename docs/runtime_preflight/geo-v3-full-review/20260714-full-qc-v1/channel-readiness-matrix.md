# Channel Readiness Matrix - 20260714-full-qc-v1

| Channel | Task key | Task record | Generation | Final package | Unblock requirement |
| --- | --- | --- | --- | --- | --- |
| productreview.com.au | `placement.productreview.official_response` | `candidate` | `needs_evidence` | Not created | No authorised business profile and no specific customer review context were provided. |
| ozbargain.com.au | `placement.ozbargain.deal_submission` | `candidate` | `needs_evidence` | Not created | No current price, discount, stock, validity period, or merchant deal authorisation was provided. |
| quora.com | `placement.quora.disclosed_expert_answer` | `candidate` | `needs_evidence` | Not created | No authorised contributor profile or approved target question was provided. |
| advinsys.com.au | `placement.website.product_page` | `approved` | `approved` | `cf9355c3-df61-438e-9d79-db2cb044a0b6` v2 | None for the approved-content boundary. |
| amazon.com.au | `placement.amazon.listing` | `approved` | `approved` | `9184789f-081f-4689-8cbe-3d3dbf877083` v2 | None for the approved-content boundary. |
| youtube.com | `placement.youtube.video_script` | `approved` | `approved` | `0ddc3830-2ad8-4a6b-88c6-8930f9d974cf` v2 | None for the approved-content boundary. |
| tiktok.com | `placement.tiktok.short_video` | `approved` | `approved` | `f66660e4-5bc7-4bcc-a835-7eb7dc2fab84` v2 | None for the approved-content boundary. |
| instagram.com | `placement.instagram.social_post` | `approved` | `approved` | `0f719126-22b7-4c8c-9c08-5fffaf5141fe` v1 | None for the approved-content boundary. |
| reddit.com | `placement.reddit.disclosed_official_post` | `approved` | `approved` | `b70b7876-0d6c-4237-bcd1-376f6a16aeb3` v2 | None for the approved-content boundary. |

## Gate semantics

A `candidate` task is a real, persisted channel task, but it cannot create an Opportunity or content package until its publisher policy and prerequisites are approved.
No row in this matrix represents an external post. Automated posting is prohibited for every channel.
