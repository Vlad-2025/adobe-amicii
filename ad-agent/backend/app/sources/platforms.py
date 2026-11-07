"""What each platform's official API actually gives you. Drives the 'Connect a channel' screen and
explains, per platform, which parts of this app work on real data and how.
Facts checked in Nov 2026; platforms change access rules often, so re-check before relying on them."""
from __future__ import annotations

PLATFORMS: dict[str, dict] = {
    "instagram": {
        "name": "Instagram", "kind": "ads", "api": "Meta Marketing API (ads) + Instagram Graph API (organic)",
        "auth": "Meta business app + system-user token (ads_read; ads_management to change budgets)",
        "access": "Limited access for your own ad accounts out of the box; Full access for client accounts needs App Review + Business Verification.",
        "cost": "Free API; you pay for the ads.",
        "reports": "Daily insights per campaign / ad set / ad: impressions, reach, frequency, clicks, spend, conversions (pixel / Conversions API).",
        "breakdowns": "Age, gender, country/region, placement, device. Interest-based ad sets act as audience segments.",
        "audience": "Aggregated only. Follower demographics (age, gender, top cities/countries) for your own Business account. Never a list of individual followers.",
        "latency_days": 0, "comments": "Comments on your ad posts via the Graph API (page access).",
    },
    "facebook": {
        "name": "Facebook", "kind": "ads", "api": "Meta Marketing API",
        "auth": "Meta business app + system-user token (ads_read / ads_management)",
        "access": "Same as Instagram: Limited access for your own accounts; App Review for Full access.",
        "cost": "Free API; you pay for the ads.",
        "reports": "Same Insights API as Instagram (one Meta ad account usually runs both).",
        "breakdowns": "Age, gender, region, placement, device; ad sets per interest segment.",
        "audience": "Aggregated only (Page insights demographics).", "latency_days": 0, "comments": "Comments on ad posts via the Graph API.",
    },
    "tiktok": {
        "name": "TikTok", "kind": "ads", "api": "TikTok API for Business (Marketing API)",
        "auth": "TikTok for Business developer app + advertiser authorization (OAuth)",
        "access": "Developer app approval by TikTok; the advertiser grants access to their ad account.",
        "cost": "Free API; you pay for the ads.",
        "reports": "Reporting API: daily stats per campaign / ad group / ad incl. video views and conversions (TikTok Pixel / Events API).",
        "breakdowns": "Age, gender, country, placement, interest category (per ad group).",
        "audience": "Aggregated audience reports only.", "latency_days": 1, "comments": "Ad comments via the comment management endpoints.",
    },
    "x": {
        "name": "X", "kind": "ads", "api": "X Ads API (campaigns, analytics) + X API v2 (posts, listening)",
        "auth": "X developer account + Ads API access approval; OAuth for the ad account",
        "access": "Ads API access is requested separately from the regular X API.",
        "cost": "X API v2 is pay-per-use since Feb 2026 (no free tier); Ads API for analytics on your own ad account.",
        "reports": "Stats per campaign / line item / promoted post: impressions, engagements, clicks, spend, conversions (X Pixel).",
        "breakdowns": "Targeting segments (keywords, interests, follower look-alikes) per line item; age/gender/location audience summaries.",
        "audience": "Aggregated. Public posts can be read via the paid X API for listening.", "latency_days": 1, "comments": "Replies to promoted posts via X API v2 (paid reads).",
    },
    "linkedin": {
        "name": "LinkedIn", "kind": "ads", "api": "LinkedIn Marketing API (Advertising + Reporting)",
        "auth": "LinkedIn developer app with Advertising API product approval; OAuth (r_ads, r_ads_reporting, rw_ads)",
        "access": "Advertising API access requires an application and LinkedIn approval.",
        "cost": "Free API; you pay for the ads (CPMs are high, often €25-40).",
        "reports": "adAnalytics: impressions, clicks, spend, leads/conversions per campaign / creative, daily.",
        "breakdowns": "Professional demographics (job function, seniority, industry, company size) per campaign — the main B2B advantage.",
        "audience": "Aggregated professional demographics; minimum thresholds hide small groups.", "latency_days": 1, "comments": "Comments on sponsored content via the Community Management API.",
    },
    "bluesky": {
        "name": "Bluesky", "kind": "audience", "api": "AT Protocol public AppView (public.api.bsky.app)",
        "auth": "None for public reads; app password for search.",
        "access": "Open: follows, posts and starter packs are public by design.",
        "cost": "Free.",
        "reports": "No ads: Bluesky has no native ad product (as of mid-2026). Used as an audience source.",
        "breakdowns": "Communities detected from the real follow graph and posts.",
        "audience": "Individual public accounts, follows and posts (we hash IDs and only show aggregates).", "latency_days": 0, "comments": "Public replies.",
    },
    "listening": {
        "name": "Social listening", "kind": "audience", "api": "Brandwatch / Talkwalker / Meltwater / Sprinklr APIs, or Reddit / X paid APIs",
        "auth": "Vendor API key (enterprise contract)", "access": "Commercial licence.", "cost": "Paid, typically enterprise pricing.",
        "reports": "Topic, keyword and sentiment volumes across public platforms.",
        "breakdowns": "Communities and topics from public conversations.", "audience": "Aggregated public conversation data.", "latency_days": 0, "comments": "—",
    },
}

AD_PLATFORMS = [k for k, v in PLATFORMS.items() if v["kind"] == "ads"]
