"""High-sell-probability visual areas for Adobe Stock.

Each area: evergreen commercial demand + current buyers. The agent searches
ONLY inside these areas (seeds, mapping, filtering) so effort concentrates
where stock actually sells. Areas are reviewed each cycle: an area with zero
nuggets accepted across N cycles gets demoted (see agent.review_areas).

Every area declares `toplist_sites` — relatable product sites with top/best-
seller lists the agent harnesses when the area yields little from other
sources (demand-driven source expansion).
"""

AREAS = {
    "autumn_fashion": {
        "label": "Autumn / transitional fashion",
        "why": "Seasonal wardrobe refresh is the #1 recurring stock-apparel demand; buyers license outfit + knitwear shots Aug-Nov.",
        "seeds": ["autumn outfit", "knit sweater style", "transitional coat"],
        "match": ["autumn", "fall outfit", "sweater", "knit", "coat", "scarf", "layering", "corduroy", "boots"],
        "toplist_sites": ["https://www.nordstrom.com/tops-women-clothing"],
    },
    "teen_fashion": {
        "label": "Teen fashion",
        "why": "Teen style drives the fastest trend cycles and social-first stock demand; back-to-school + festival micro-seasons.",
        "seeds": ["teen fashion", "teen outfit", "girl fashion"],
        "match": ["teen", "y2k", "middle part", "school outfit", "teenage", "aesthetic outfit"],
        "toplist_sites": ["https://www.shein.com/topseller.html"],
    },
    "linen_summer": {
        "label": "Linen & natural fabrics",
        "why": "Linen has held multi-year demand growth; every summer cycle needs fresh linen lifestyle shots.",
        "seeds": ["linen dress", "linen shirt", "natural fabric outfit"],
        "match": ["linen", "cotton", "natural fabric", "white dress", "midi dress"],
        "toplist_sites": ["https://www.zalando.co.uk/womens-dresses-trending/"],
    },
    "matcha_drinks": {
        "label": "Matcha & specialty drinks",
        "why": "Matcha is a multi-year breakout; cafe/beverage is the highest-turnover food stock niche.",
        "seeds": ["iced matcha", "matcha latte", "specialty coffee drink"],
        "match": ["matcha", "iced tea", "cold brew", "bubble tea", "cafe"],
        "toplist_sites": ["https://www.ebay.com/deals"],
    },
    "street_food": {
        "label": "Street food & casual dining",
        "why": "Street food and casual dining license heavily for delivery apps, menus, food blogs; high turnover, constant fresh demand.",
        "seeds": ["street food", "food trend", "viral food"],
        "match": ["street food", "viral food", "food trend", "snack", "wrap", "taco", "burger", "noodles", "dumpling", "bakery", "pastry"],
        "toplist_sites": ["https://www.ebay.com/deals"],
    },
    "warm_kitchen": {
        "label": "Warm-metal kitchens & home decor",
        "why": "Copper/brass kitchen and sage/terracotta decor dominate current interior licensing.",
        "seeds": ["copper kitchen", "sage green decor", "terracotta kitchen"],
        "match": ["copper", "brass", "kitchen", "decor", "sage", "terracotta", "faucet", "backsplash", "interior"],
        "toplist_sites": ["https://www.westwing.de/trends/"],
    },
    "interiors": {
        "label": "Interiors & home styling",
        "why": "Interior lifestyle stock sells year-round to furniture/retail campaigns; trend-led colorways command premium.",
        "seeds": ["home interior trend", "living room ideas", "bedroom decor"],
        "match": ["interior", "living room", "bedroom", "sofa", "rug", "curtain", "vase", "shelf", "gallery wall", "home decor"],
        "toplist_sites": ["https://www.ikea.com/us/en/new-products/"],
    },
    "crochet_craft": {
        "label": "Crochet & handmade craft",
        "why": "Crochet bags exploded since 2023 and are still pre-peak; craft licensing is strong and under-supplied.",
        "seeds": ["crochet bag", "crochet pattern", "handmade craft"],
        "match": ["crochet", "handmade", "craft", "knitting", "yarn", "pattern", "bag"],
        "toplist_sites": ["https://www.lovecrafts.com/en-gb/bestsellers"],
    },
    "travel": {
        "label": "Travel & destinations",
        "why": "Travel stock sells constantly to tourism boards, airlines, hotels; shoulder-season destinations trend pre-summer.",
        "seeds": ["kyoto autumn", "amalfi coast", "iceland northern lights",
                  "lisbon travel", "albanian riviera", "santorini",
                  "patagonia trek", "morocco desert tour", "japan cherry blossom",
                  "maldives overwater", "swiss alps summer", "costa rica jungle",
                  "safari kenya", "bali rice terrace", "porto weekend",
                  "lofoten islands", "hokkaido snow", "tulum cenote"],
        "match": ["travel", "destination", "itinerary", "trip", "vacation", "carry-on", "packing", "resort", "safari", "city break",
                  "kyoto", "amalfi", "iceland", "lisbon", "albania", "santorini", "patagonia", "morocco", "maldives", "swiss alps", "costa rica", "kenya", "bali", "porto", "lofoten", "hokkaido", "tulum", "japan", "cherry blossom", "northern lights", "rice terrace", "desert tour", "cenote"],
        "toplist_sites": ["https://www.expedia.com/deals"],
    },
    "gadgets": {
        "label": "Gadgets & tech accessories",
        "why": "Gadget lifestyle shots (in-hand, on-desk, in-use) license to tech marketing year-round; product-forward stock is under-supplied.",
        "seeds": ["portable projector", "mechanical keyboard", "esk8",
                  "smart ring", "bone conduction headphones", "portable monitor",
                  "espresso maker portable", "drone camera", "power bank",
                  "phone gimbal", "desk setup accessories", "e-reader",
                  "action camera", "smart home sensor"],
        "match": ["gadget", "tech", "phone case", "earbuds", "speaker", "charger", "smartwatch", "desk setup", "keyboard", "drone",
                  "projector", "smart ring", "bone conduction", "portable monitor", "espresso maker", "power bank", "gimbal", "e-reader", "action camera", "sensor", "mechanical keyboard"],
        "toplist_sites": ["https://www.ebay.com/deals"],
    },
    "accessories": {
        "label": "Accessories & bags",
        "why": "Accessory close-ups are the highest-ROI stock shot type; bag/jewelry trends drive repeat licensing.",
        "seeds": ["accessory trend", "bag trend", "jewelry trend"],
        "match": ["bag", "handbag", "tote", "purse", "jewelry", "earrings", "necklace", "bracelet", "sunglasses", "belt", "watch strap"],
        "toplist_sites": ["https://www.shein.com/topseller.html"],
    },
    "hairstyles": {
        "label": "Hairstyles & hair care",
        "why": "Hair trend stock licenses to salons, product campaigns, and editorial; bob/layer/cut trends spike with seasons.",
        "seeds": ["wolf cut", "curtain bangs", "bixie cut", "butterfly haircut",
                  "chelsea cut", " Italian bob", "elephant cut", "liquid hair",
                  "glass hair", "cherry cola hair", "brunette balayage",
                  "bottleneck bangs", "jellyfish haircut"],
        "match": ["hairstyle", "haircut", "bob", "layers", "bangs", "balayage", "curtain bangs", "wolf cut", "hair color", "blonde", "brunette", "curly hair"],
        "toplist_sites": ["https://www.sallybeauty.com/trending-now.html"],
    },
    "beauty_makeup": {
        "label": "Beauty & makeup trends",
        "why": "Beauty editorial has constant demand: seasonal lip looks, glazed/dewy skin, bold liner all license heavily for cosmetics campaigns.",
        "seeds": ["latte makeup", "espresso makeup", "strawberry makeup",
                  "siren eyes", "doe eyes makeup", "soap brows",
                  "laminated brows", "brown lip liner", "glazed lips",
                  "cold girl makeup", "cherry cola lips", "sunburn blush",
                  "peach fuzz makeup", "cream blush draping", "glass skin",
                  "clean girl makeup", "dewy skin", "latte eyes",
                  "microblading brows", "flutter lashes", "smoked liner",
                  "glazed donut skin", "mocha mousse makeup"],
        "match": ["makeup", "eyes", "brows", "lashes", "lip liner", "lips",
                  "blush", "liner", "mascara", "foundation", "serum",
                  "beauty", "perfume", "fragrance", "glazed", "dewy",
                  "skincare", "latte makeup", "espresso makeup",
                  "strawberry makeup", "siren eyes", "soap brows",
                  "laminated brows", "microblading", "sunburn blush",
                  "cold girl", "glass skin", "clean girl"],
        "toplist_sites": ["https://www.sallybeauty.com/trending-now.html"],
    },
    "nails_detail": {
        "label": "Nail trends",
        "why": "Nail art is a high-volume search vertical; seasonal designs (chrome, aura, milky) trend quarterly and macro detail sells.",
        "seeds": ["nail trend", "nail design", "gel nails"],
        "match": ["nails", "manicure", "nail art", "gel nail",
                  "nail design", "chrome nail", "french tip", "nail polish",
                  "pedicure"],
        "toplist_sites": ["https://www.sallybeauty.com/trending-now.html"],
    },
    "drinks": {
        "label": "Drinks & cocktails",
        "why": "Beverage stock is a steady commercial vertical for bars/brands; craft mocktail + low-alb trends are rising.",
        "seeds": ["cocktail trend", "mocktail", "drink recipe trend"],
        "match": ["cocktail", "mocktail", "spritz", "espresso martini", "negroni", "lemonade", "soda", "kombucha", "sparkling drink", "drink"],
        "toplist_sites": ["https://www.ebay.com/deals"],
    },
    "colors": {
        "label": "Color trends",
        "why": "Color-of-the-year moments (butter yellow, mocha mousse) create instant demand for color-forward lifestyle stock.",
        "seeds": ["color of the year", "mocha mousse", "trend color 2026"],
        "match": ["butter yellow", "mocha mousse", "cherry red lips",
                  "color trend", "pastel", "earth tone", "color of the year"],
        "toplist_sites": ["https://www.pantone.com/color-of-the-year"],
    },
    "adult_lingerie": {
        "label": "Lingerie & intimate apparel (SFW commercial)",
        "why": "Lingerie sells steadily as SFW campaign stock (product, detail, fabric shots); body-positive and bridal-adjacent niches growing.",
        "seeds": ["silk slip dress", "lace bodysuit", "sheer lingerie",
                  "strapless bra trend", "satin pyjama set", "bridal lingerie",
                  "corset top outfit", "lace trim camisole", "silk robe set",
                  "body positive lingerie", "seamless bralette", "silk cami set",
                  "mesh bodysuit", "satin slip skirt", "velvet loungewear set"],
        "match": ["lingerie", "bralette", "bodysuit", "intimates",
                  "slip dress", "slip skirt", "silk robe", "silk cami",
                  "camisole", "sleepwear", "loungewear", "stockings",
                  "corset", "satin", "mesh bodysuit", "pajama", "pyjama",
                  "velvet loungewear"],
        "toplist_sites": ["https://www.shein.com/topseller.html"],
    },
    "costume_cosplay": {
        "label": "Costume & cosplay trends",
        "why": "Cosplay/costume is a rising licensed-vertical with con-season spikes; generic (unbranded) costume stock is under-supplied.",
        "seeds": ["cosplay costume", "halloween costume trend", "anime cosplay"],
        "match": ["cosplay", "costume", "halloween", "anime", "manga", "kigurumi", "roleplay", "convention"],
        "toplist_sites": ["https://www.halloweencostumes.com/best-sellers.html"],
    },
    "styles": {
        "label": "Aesthetic styles & subcultures",
        "why": "Named aesthetics (coquette, gorpcore, balletcore) drive search demand before filtering into mainstream fashion.",
        "seeds": ["aesthetic style", "gorpcore", "coquette style"],
        "match": ["aesthetic", "coquette", "gorpcore", "balletcore", "old money", "clean girl", "cottagecore", "y2k", "streetwear", "quiet luxury"],
        "toplist_sites": ["https://www.shein.com/topseller.html"],
    },
    "yellow_color": {
        "label": "Butter yellow & color-trend fashion",
        "why": "Butter yellow is the declared breakout colorway this year — early-stage, pre-peak, low supply on stock sites.",
        "seeds": ["butter yellow", "yellow dress", "yellow outfit"],
        "match": ["butter yellow", "yellow dress", "yellow outfit", "mustard", "pastel yellow"],
        "toplist_sites": ["https://www.pantone.com/color-of-the-year"],
    },
}

# report categories group areas for the consumer app
CATEGORY_OF_AREA = {
    "fashion": ["autumn_fashion", "teen_fashion", "linen_summer", "styles", "yellow_color", "adult_lingerie", "costume_cosplay"],
    "beauty": ["beauty_makeup", "nails_detail", "hairstyles"],
    "interiors": ["warm_kitchen", "interiors"],
    "food_drinks": ["matcha_drinks", "street_food", "drinks"],
    "lifestyle": ["travel", "gadgets", "accessories", "crochet_craft", "colors"],
}


def match_area(title):
    """Return area key for a title, or None.

    Word-boundary matching; when several areas hit, the one with the LONGEST
    matched term wins (most specific: 'latte makeup' -> beauty, not drinks)."""
    import re as _re
    t = " " + _re.sub(r"[^a-z0-9]+", " ", title.lower()).strip() + " "
    best = None
    best_len = 0
    for key, a in AREAS.items():
        for m in a["match"]:
            m = _re.sub(r"[^a-z0-9]+", " ", m.strip().lower()).strip()
            if m and " " + m + " " in t and len(m) > best_len:
                best = key
                best_len = len(m)
    return best


def area_seeds():
    out = []
    for a in AREAS.values():
        out.extend(a["seeds"])
    return out


def current_season():
    """Northern-hemisphere season for seed rotation."""
    import time
    m = time.gmtime().tm_mon
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    if m in (9, 10, 11):
        return "autumn"
    return "winter"


def seasonal_seeds():
    """Season-rotated variants of generic seeds so the harvest changes
    through the year (autumn hairstyles != summer hairstyles)."""
    season = current_season()
    import time
    year = time.gmtime().tm_year
    bases = ["hairstyle", "hair color", "outfit", "nails", "makeup look",
             "dress trend", "wedding guest", "party makeup", "lip trend",
             "knitwear", "coat trend", "fragrance"]
    return [f"{b} {season} {year}" for b in bases] + [
        f"{b} trends {season}" for b in bases[:6]]
