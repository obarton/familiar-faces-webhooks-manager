"""Anthropic (Claude) integration for AI competitor summaries.

Same fault-tolerance contract as the other client modules: a lazily-built
singleton client from an env-var key, every call wrapped so failures log and
return None instead of raising. No ANTHROPIC_API_KEY = feature degrades to a hint.

Generates a short brand-aware analysis of a competitor from its tracked content:
what they post and how it relates to your brand (settings.BRAND_*).
"""
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_client = None

# A bounded summary — enough for two short sections, cheap and fast.
_MAX_TOKENS = 1500
# How many recent items to feed the model as evidence.
_ITEMS_FOR_SUMMARY = 30


def is_configured():
    return bool(getattr(settings, 'ANTHROPIC_API_KEY', ''))


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    # Imported lazily so the app boots without the anthropic package installed.
    import anthropic
    _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _content_digest(items):
    """Condense recent content items into a compact evidence block."""
    lines = []
    for it in items[:_ITEMS_FOR_SUMMARY]:
        parts = [it.format_label]
        if it.published_date:
            parts.append(it.published_date.isoformat())
        head = ' · '.join(parts)
        title = (it.title or it.url).strip().replace('\n', ' ')[:180]
        line = f'- [{head}] {title}'
        if it.summary:
            line += f' ({it.summary})'
        if it.keywords:
            line += f' #{" #".join(it.keywords[:6])}'
        lines.append(line)
    return '\n'.join(lines) if lines else '(no content tracked yet)'


def _brand_digest(exclude_id=None):
    """A digest of our own brand accounts' recent content, or '' if none tracked."""
    from django.db.models import F
    from .models import CompetitorContentItem, CompetitorSource

    brand_sources = list(CompetitorSource.objects.filter(is_own_brand=True).exclude(id=exclude_id))
    if not brand_sources:
        return ''
    items = list(
        CompetitorContentItem.objects
        .filter(source__in=brand_sources)
        .order_by(F('published_date').desc(nulls_last=True), '-created_at')[:_ITEMS_FOR_SUMMARY]
    )
    return _content_digest(items) if items else ''


def summarize_competitor(source, items):
    """Return an AI analysis string for `source`, or None on failure.

    For an own-brand account it's a self-analysis; for a competitor it's a
    comparison grounded in our own brand's tracked content when available.
    """
    client = _get_client()
    if not client:
        logger.warning('AI summary skipped: ANTHROPIC_API_KEY not set. source=%r', source.name)
        return None

    brand_name = getattr(settings, 'BRAND_NAME', 'our brand')
    brand_description = getattr(settings, 'BRAND_DESCRIPTION', '')
    channels = ', '.join(c['label'] for c in source.channels) or 'none'

    if source.is_own_brand:
        system = (
            f'You are a marketing strategist for {brand_name}, analyzing OUR OWN brand '
            f'account for the marketing team.\n\nOUR BRAND — {brand_name}: {brand_description}\n\n'
            f'Write in plain text (no markdown symbols, no bullet characters). Use exactly '
            f'two sections, each led by a short label on its own line:\n'
            f'"Content themes" — 2-3 sentences on what this account posts: formats, topics, '
            f'cadence, and what is resonating (use engagement signals).\n'
            f'"Gaps and opportunities" — 2-4 sentences on what we are under-using and concrete '
            f'ideas to test next.\n'
            f'Keep the whole response under 220 words. Ground every claim in the content; '
            f'do not invent facts.'
        )
        user = (
            f'Our account: {source.name}\n'
            f'Channels tracked: {channels}\n\n'
            f'Recent content (most recent first):\n{_content_digest(items)}'
        )
    else:
        brand = _brand_digest()
        grounding = (
            'You are also given OUR OWN recent content below — ground the "How they relate" '
            'section in concrete differences between their content and ours.'
            if brand else
            ''
        )
        system = (
            f'You are a marketing strategist for {brand_name}. Analyze a competitor for '
            f'the marketing team.\n\nOUR BRAND — {brand_name}: {brand_description}\n{grounding}\n\n'
            f'Write in plain text (no markdown symbols, no bullet characters). Use exactly '
            f'two sections, each led by a short label on its own line:\n'
            f'"Overview" — 2-3 sentences on the competitor: positioning, content themes, '
            f'formats, cadence, and audience, grounded in the content provided.\n'
            f'"How they relate to {brand_name}" — 2-4 sentences on overlap, how they '
            f'differ, and the clearest threat or opportunity for {brand_name}.\n'
            f'Keep the whole response under 220 words. Ground every claim in the content; '
            f'do not invent facts.'
        )
        user = (
            f'Competitor: {source.name}\n'
            f'Channels tracked: {channels}\n\n'
            f'Recent content (most recent first):\n{_content_digest(items)}'
        )
        if brand:
            user += f'\n\nOUR OWN ({brand_name}) recent content:\n{brand}'

    try:
        response = client.messages.create(
            model=getattr(settings, 'COMPETITOR_AI_MODEL', 'claude-opus-4-8'),
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{'role': 'user', 'content': user}],
        )
        if response.stop_reason == 'refusal':
            logger.warning('AI summary refused for source %r', source.name)
            return None
        text = next((b.text for b in response.content if b.type == 'text'), '').strip()
        return text or None
    except Exception:
        logger.warning('AI summary generation failed for source %r', source.name, exc_info=True)
        return None


def generate_and_store(source, items):
    """Generate a summary and cache it on the source. Returns True on success."""
    summary = summarize_competitor(source, items)
    if not summary:
        return False
    source.ai_summary = summary
    source.ai_summary_generated_at = timezone.now()
    source.save(update_fields=['ai_summary', 'ai_summary_generated_at', 'updated_at'])
    return True


# --- Competitive landscape report (web-search grounded) ---------------------

_LANDSCAPE_MAX_TOKENS = 4500
_LANDSCAPE_ITEMS_PER_SOURCE = 8
# Web search runs a server-side loop; if it hits the iteration cap the response
# comes back as pause_turn and we re-send to continue.
_MAX_PAUSE_CONTINUATIONS = 6


def _accounts_block():
    from django.db.models import F
    from .models import CompetitorContentItem, CompetitorSource

    blocks = []
    for s in CompetitorSource.objects.order_by('-is_own_brand', 'name'):
        role = 'US — our own brand' if s.is_own_brand else 'competitor'
        handles = '; '.join(f"{c['label']} {c['url']}" for c in s.channels) or 'none'
        items = list(
            CompetitorContentItem.objects.filter(source=s)
            .order_by(F('published_date').desc(nulls_last=True), '-created_at')[:_LANDSCAPE_ITEMS_PER_SOURCE]
        )
        blocks.append(
            f'### {s.name} [{role}]\nChannels: {handles}\n'
            f'Recent tracked content:\n{_content_digest(items)}'
        )
    return '\n\n'.join(blocks)


def _extract_report_text(response):
    """Pull the final report out of a web-search response, dropping the model's
    inter-search narration ("Let me search…") that arrives as text blocks."""
    parts = []
    for block in response.content:
        t = getattr(block, 'type', '')
        if t == 'text':
            parts.append(block.text)
        elif t == 'server_tool_use' or 'tool' in t:
            # A search happened — anything narrated before it isn't the report.
            parts = []
    text = '\n'.join(parts).strip()
    if not text:  # fallback: everything, then trim below
        text = '\n'.join(b.text for b in response.content if getattr(b, 'type', '') == 'text').strip()

    # Trim any remaining leading narration before the first Markdown heading/quote
    # (our report always starts with a heading or blockquote).
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith('#') or s.startswith('>'):
            return '\n'.join(lines[i:]).strip()
    return text


def generate_landscape():
    """Generate a markdown competitive-landscape report across all tracked
    accounts, grounded in web search. Returns the markdown string or None."""
    client = _get_client()
    if not client:
        logger.warning('Landscape skipped: ANTHROPIC_API_KEY not set.')
        return None

    from .models import CompetitorSource
    if not CompetitorSource.objects.exists():
        return None

    brand_name = getattr(settings, 'BRAND_NAME', 'our brand')
    brand_description = getattr(settings, 'BRAND_DESCRIPTION', '')
    owner = getattr(settings, 'BRAND_OWNER', '')
    tldr_label = f'TL;DR for {owner}' if owner else 'TL;DR'

    system = (
        f'You are a competitive-intelligence analyst for {brand_name}.\n\n'
        f'OUR BRAND — {brand_name}: {brand_description}\n\n'
        f'You are given our brand plus the competitor accounts we track, each with '
        f'their social handles and a sample of recent tracked content. Use web search '
        f'to gather CURRENT, directional context on each: approximate follower counts '
        f'(Instagram / TikTok / YouTube), founding year and HQ, active cities, recent or '
        f'upcoming events/tours, membership or loyalty programs, and notable press. '
        f'Treat every figure as approximate and directional — never present a follower '
        f'count as exact.\n\n'
        f'Write the report in GitHub-flavored Markdown with these sections, in order:\n\n'
        f'## {tldr_label}\n'
        f'3-5 sentences: which tier {brand_name} sits in, the biggest threats and why, '
        f'and our clearest edge and clearest gap.\n\n'
        f'## Snapshot Table\n'
        f'A markdown table, columns: Brand | IG (approx) | Other social | Founded / HQ | '
        f'Active cities | Positioning. One row per account; bold our brand and mark it "(us)".\n\n'
        f'## Where each competitor stands\n'
        f'For each competitor (not our own brand), a "### Name — one-line role" subsection '
        f'with bolded leads **Social:**, **Events/expansion:**, and **Watch:** (2-4 sentences total).\n\n'
        f'## Implications for {brand_name}\n'
        f'4-6 bullet takeaways tied to specific competitors: our gaps, head-to-head geographic '
        f'overlaps, loyalty/monetization benchmarks, and prestige/scale aspirations.\n\n'
        f'End with a one-line italic sources note. Ground every claim in the tracked content '
        f'and your web search; keep it tight and skimmable; do not invent precise numbers.\n\n'
        f'Output ONLY the report itself, beginning directly with the first "## " heading. Do not '
        f'narrate your research, describe or comment on your searches, or add any preamble or '
        f'closing remarks outside the report.'
    )
    user = (
        f'Our brand is {brand_name}. Accounts to cover:\n\n{_accounts_block()}\n\n'
        f'Research each with web search, then produce the landscape report.'
    )
    tools = [{'type': 'web_search_20260209', 'name': 'web_search'}]
    model = getattr(settings, 'COMPETITOR_AI_MODEL', 'claude-opus-4-8')

    try:
        messages = [{'role': 'user', 'content': user}]
        response = client.messages.create(
            model=model, max_tokens=_LANDSCAPE_MAX_TOKENS, system=system,
            messages=messages, tools=tools,
        )
        # Continue the server-side web-search loop if it paused.
        continuations = 0
        while response.stop_reason == 'pause_turn' and continuations < _MAX_PAUSE_CONTINUATIONS:
            messages.append({'role': 'assistant', 'content': response.content})
            response = client.messages.create(
                model=model, max_tokens=_LANDSCAPE_MAX_TOKENS, system=system,
                messages=messages, tools=tools,
            )
            continuations += 1

        if response.stop_reason == 'refusal':
            logger.warning('Landscape report refused')
            return None
        return _extract_report_text(response) or None
    except Exception:
        logger.warning('Landscape report generation failed', exc_info=True)
        return None


def generate_and_store_landscape():
    """Generate the landscape report into the singleton row, tracking status.

    Runs off the request path (called by the refresh_competitors worker); slow
    because of web search. Returns True on success. Records status/last_error on
    the row so the UI can show progress and failures.
    """
    from .models import LandscapeReport

    report = LandscapeReport.get_solo()
    report.status = LandscapeReport.STATUS_GENERATING
    report.save(update_fields=['status', 'updated_at'])

    markdown = generate_landscape()

    report.generation_requested = False
    if not markdown:
        report.status = LandscapeReport.STATUS_FAILED
        report.last_error = 'Generation returned no report — check the logs (API error, refusal, or no accounts).'
        report.save(update_fields=['status', 'last_error', 'generation_requested', 'updated_at'])
        return False

    report.markdown = markdown
    report.status = LandscapeReport.STATUS_READY
    report.last_error = ''
    report.generated_at = timezone.now()
    report.save(update_fields=[
        'markdown', 'status', 'last_error', 'generated_at', 'generation_requested', 'updated_at',
    ])
    return True
