from __future__ import annotations

from uuid import uuid5, NAMESPACE_URL

from geno_core.models import MarketProfile, PromptQuestion


PROMPT_VERSION_AU_DTC_V1 = "au_dtc_ecommerce_v1"

INTENT_WEIGHTS: dict[str, float] = {
    "brand_awareness": 0.90,
    "category_recommendation": 1.00,
    "city_category_recommendation": 1.00,
    "competitor_comparison": 0.95,
    "purchase_decision": 0.95,
    "review_reputation": 0.85,
    "price": 0.80,
    "service_coverage": 0.75,
    "local_trust": 0.90,
    "alternative": 0.90,
}


def _prompt_id(project_id: str, index: int, text: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"geno:prompt:{project_id}:{index}:{text}"))


def _city_cycle(market_profile: MarketProfile) -> list[str]:
    required = ["Sydney", "Melbourne", "Brisbane"]
    available = set(market_profile.cities)
    missing = [city for city in required if city not in available]
    if missing:
        raise ValueError(f"AU market profile is missing required prompt cities: {missing}")
    return required


def _competitor_cycle(competitors: tuple[str, ...]) -> list[str]:
    if len(competitors) < 3 or len(competitors) > 5:
        raise ValueError("M1 Prompt Pack requires 3-5 competitors")
    return list(competitors)


def build_au_dtc_prompt_pack(
    *,
    project_id: str,
    market_profile: MarketProfile,
    industry_code: str,
    target_brand: str,
    category: str,
    competitors: tuple[str, ...],
    prompt_version: str = PROMPT_VERSION_AU_DTC_V1,
) -> tuple[PromptQuestion, ...]:
    cities = _city_cycle(market_profile)
    competitor_names = _competitor_cycle(competitors)
    prompts: list[tuple[str, str, str, int]] = []

    templates = [
        (
            "brand_awareness",
            [
                "Is {brand} good in Australia?",
                "What is {brand} known for in Australia?",
                "Do Australians recommend {brand}?",
                "Is {brand} a trusted {category} brand in Australia?",
                "How does {brand} compare for Australian shoppers?",
                "Is {brand} popular in {city}?",
                "What should Australian customers know about {brand}?",
                "Does {brand} have a good reputation in Australia?",
                "Is {brand} suitable for Australian buyers?",
                "What are the pros and cons of {brand} in Australia?",
            ],
        ),
        (
            "category_recommendation",
            [
                "Best {category} in Australia",
                "Top {category} brands for Australian customers",
                "Which {category} should I buy in Australia?",
                "Recommended {category} brands in Australia",
                "Most trusted {category} options in Australia",
                "Best value {category} in Australia",
                "Best premium {category} brands in Australia",
                "Best online {category} stores in Australia",
                "Best {category} for first-time buyers in Australia",
                "Best {category} with Australian shipping",
            ],
        ),
        (
            "city_category_recommendation",
            [
                "Best {category} in {city}",
                "Top {category} brands serving {city}",
                "Where to buy {category} in {city}",
                "Best online {category} delivery to {city}",
                "Recommended {category} for shoppers in {city}",
                "Best value {category} available in {city}",
                "Best {category} brands with fast shipping to {city}",
                "Which {category} is best for customers in {city}?",
                "Best reviewed {category} brands in {city}",
                "Best alternatives for {category} in {city}",
            ],
        ),
        (
            "competitor_comparison",
            [
                "{brand} vs {competitor} Australia",
                "Is {brand} better than {competitor}?",
                "{brand} or {competitor} for Australian customers",
                "{brand} vs {competitor} price Australia",
                "{brand} vs {competitor} reviews Australia",
                "{brand} vs {competitor} shipping Australia",
                "{brand} vs {competitor} quality comparison",
                "{brand} vs {competitor} for {category}",
                "Should I choose {brand} or {competitor} in Australia?",
                "{brand} alternatives compared with {competitor}",
            ],
        ),
        (
            "purchase_decision",
            [
                "Is {brand} worth it?",
                "Should I buy from {brand} in Australia?",
                "Is {brand} worth the price in Australia?",
                "Who should buy {brand}?",
                "Is {brand} good value for Australian shoppers?",
                "Is {brand} reliable for online orders in Australia?",
                "What makes {brand} worth buying?",
                "Is {brand} better for budget or premium buyers?",
                "Would you recommend {brand} for {category}?",
                "Is {brand} a good choice in {city}?",
            ],
        ),
        (
            "review_reputation",
            [
                "{brand} reviews Australia",
                "What do Australian customers say about {brand}?",
                "Is {brand} well reviewed in Australia?",
                "{brand} customer complaints Australia",
                "{brand} review summary",
                "Are {brand} reviews trustworthy?",
                "{brand} ProductReview Australia",
                "{brand} Reddit reviews Australia",
                "{brand} YouTube reviews Australia",
                "Common issues with {brand} in Australia",
            ],
        ),
        (
            "price",
            [
                "{category} price Australia",
                "{brand} price Australia",
                "Is {brand} expensive in Australia?",
                "Cheapest way to buy {brand} in Australia",
                "{brand} discount Australia",
                "{brand} sale Australia",
                "{brand} price compared with {competitor}",
                "Best value {category} brands Australia",
                "How much does {brand} cost in Australia?",
                "{brand} pricing and shipping Australia",
            ],
        ),
        (
            "service_coverage",
            [
                "Does {brand} ship to Australia?",
                "Does {brand} ship to {city}?",
                "{brand} delivery time Australia",
                "{brand} returns policy Australia",
                "{brand} warranty Australia",
                "{brand} customer support Australia",
                "Can I buy {brand} online in Australia?",
                "{brand} shipping cost Australia",
                "Does {brand} offer fast delivery in {city}?",
                "{brand} stock availability Australia",
            ],
        ),
        (
            "local_trust",
            [
                "Is {brand} legit in Australia?",
                "Is {brand} safe to buy from in Australia?",
                "Is {brand} an Australian business?",
                "Does {brand} have Australian customer support?",
                "Is {brand} trusted by Australian shoppers?",
                "Does {brand} comply with Australian consumer expectations?",
                "Is {brand} reliable for customers in {city}?",
                "Where can I verify {brand} in Australia?",
                "Is {brand} recommended by Australian sources?",
                "What local proof does {brand} have in Australia?",
            ],
        ),
        (
            "alternative",
            [
                "Alternatives to {competitor} in Australia",
                "Best alternatives to {brand} in Australia",
                "{brand} alternatives Australia",
                "{competitor} alternatives for Australian shoppers",
                "Brands like {brand} in Australia",
                "Better alternatives to {competitor} for {category}",
                "Best {category} alternatives with Australian shipping",
                "Local alternatives to {brand} in {city}",
                "What should I buy instead of {competitor}?",
                "Best competitors to {brand} in Australia",
            ],
        ),
    ]

    for intent_type, intent_templates in templates:
        for offset, template in enumerate(intent_templates):
            city = cities[(len(prompts) + offset) % len(cities)] if "{city}" in template else "Australia"
            competitor = competitor_names[(len(prompts) + offset) % len(competitor_names)]
            text = template.format(
                brand=target_brand,
                category=category,
                city=city,
                competitor=competitor,
            )
            prompts.append((intent_type, text, city, offset + 1))

    if len(prompts) != 100:
        raise ValueError(f"AU DTC Prompt Pack must contain 100 prompts, got {len(prompts)}")

    return tuple(
        PromptQuestion(
            id=_prompt_id(project_id, index, text),
            project_id=project_id,
            market_code=market_profile.market_code,
            industry_code=industry_code,
            text=text,
            intent_type=intent_type,
            city=city,
            language=market_profile.locale,
            target_brand=target_brand,
            competitors=competitors,
            priority=priority,
            intent_weight=INTENT_WEIGHTS[intent_type],
            prompt_version=prompt_version,
            status="active",
        )
        for index, (intent_type, text, city, priority) in enumerate(prompts, start=1)
    )
