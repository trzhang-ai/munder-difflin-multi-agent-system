'''Deterministic customer pricing.

The catalog unit_price is our cost for ONE catalog unit (sheet, piece or roll):
The ledger buys stock and values inventory at unit_price. A quote marks
that cost up and may apply a bulk discount, but never falls below cost.

MARKUP and DISCOUNT_TIERS are business assumptions, not values fitted to
quotes.csv. For scale: of the 75 requests in quote_requests.csv whose
quantities convert to catalog units, the median is about $180 at list
prices, 27% reach $500 and 17% reach $2,000. The 10% cap matches the
discount most often promised in historical quotes.
'''

import math
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
from request_schema import ParsedItems


SHEETS_PER_REAM = 500
MARKUP = 0.25
# (minimum subtotal at list prices, discount rate), largest threshold first.
DISCOUNT_TIERS = ((2000.0, 0.10), (500.0, 0.05))

if (1 + MARKUP) * (1 - max(rate for _, rate in DISCOUNT_TIERS)) <= 1:
    raise ValueError('The largest bulk discount must keep prices above cost.')


ROLL_ITEMS = frozenset({
    'Rolls of banner paper (36-inch width)',
    'Party streamers',
    'Decorative adhesive tape (washi tape)',
})
_CATEGORY_UNITS = {
    'paper': 'sheet',
    'specialty': 'sheet',
    'large_format': 'sheet',
    'product': 'piece',
}
_UNIT_ALIASES = {
    'sheets': 'sheet', 'reams': 'ream', 'boxes': 'box',
    'packs': 'pack', 'packets': 'packet', 'rolls': 'roll',
    'cartons': 'carton', 'bundles': 'bundle', 'pieces': 'piece',
    'units': 'unit', 'sets': 'set',
}
# Counting words that name one catalog product. 'pad' is excluded because a
# pad of sticky notes holds many notes.
_INDIVIDUAL_PRODUCTS = {
    'plate', 'plates', 'cup', 'cups', 'napkin', 'napkins',
    'envelope', 'envelopes', 'card', 'cards', 'flyer', 'flyers',
    'folder', 'folders', 'bag', 'bags', 'tag', 'tags',
    'notepad', 'notepads', 'note', 'notes', 'cover', 'covers',
}


def normalize_unit(value: str | None) -> str | None:
    '''Lowercase singular counting unit; one-product nouns become 'piece'.'''
    if value is None:
        return None
    value = value.strip().lower()
    if value in _INDIVIDUAL_PRODUCTS:
        return 'piece'
    return _UNIT_ALIASES.get(value, value) or None


def catalog_unit(item_name: str | None, category: str | None) -> str | None:
    '''Counting unit that the catalog unit_price refers to.'''
    if item_name in ROLL_ITEMS:
        return 'roll'
    return _CATEGORY_UNITS.get(category)


def convert_quantity(
        quantity: int | float | None,
        from_unit: str | None,
        to_unit: str | None,
        package_size: int | None = None,
        package_unit: str | None = None
    ) -> float | None:
    '''Return quantity in to_unit, or None when the conversion is unknown.

    Explicit package contents win; otherwise a ream is the trade-standard 500
    sheets. Boxes, packs and paper rolls have no standard size and stay unknown.
    '''
    from_unit, to_unit = normalize_unit(from_unit), normalize_unit(to_unit)
    package_unit = normalize_unit(package_unit)
    if (
        not isinstance(quantity, (int, float)) or isinstance(quantity, bool)
        or not math.isfinite(quantity) or quantity <= 0
        or from_unit in (None, 'unit') or to_unit in (None, 'unit')
    ):
        return None
    # One piece of a sheet-priced paper (a poster, a flyer sheet) is one sheet.
    if from_unit == to_unit or (from_unit, to_unit) == ('piece', 'sheet'):
        return float(quantity)
    if type(package_size) is int and package_size > 0 and package_unit == to_unit:
        return float(quantity * package_size)
    if package_size is None and from_unit == 'ream' and to_unit == 'sheet':
        return float(quantity * SHEETS_PER_REAM)
    return None


class QuoteLine(BaseModel):
    '''One priced catalog item.'''
    item_name: str
    quantity: int           # in catalog units
    unit: str               # sheet, piece or roll
    unit_price: float       # list price per unit, before the bulk discount
    list_total: float
    sale_price: float       # after the bulk discount; the amount to record as a sale


class UnpricedItem(BaseModel):
    '''A requested item left out of the quote, with the customer-facing reason.'''
    customer_description: str
    reason: str


class Quote(BaseModel):
    '''A priced request; cost and gross_margin are internal only.'''
    lines: list[QuoteLine]
    unpriced: list[UnpricedItem]
    subtotal: float
    discount_rate: float
    discount_amount: float
    total: float
    rationale: str
    # Internal only: for_customer() leaves these out.
    cost: float
    gross_margin: float | None

    def for_customer(self) -> dict:
        '''The quote without cost and gross_margin.'''
        return self.model_dump(exclude={'cost', 'gross_margin'})


def _money(value: float) -> float:
    '''Round to cents, half up.'''
    return float(Decimal(str(value)).quantize(Decimal('0.01'), ROUND_HALF_UP))


def discount_rate(subtotal: float) -> float:
    '''Bulk discount rate for a subtotal at list prices.'''
    return next(
        (rate for minimum, rate in DISCOUNT_TIERS if subtotal >= minimum),
        0.0,
    )


def _unpriced_reason(item, unit: str | None) -> str:
    '''Customer-facing reason an item cannot be priced yet.'''
    if item.match_status == 'not_offered':
        return 'not in our catalog'
    if item.match_status == 'needs_clarification':
        return 'please confirm which product you need'
    if item.units is None:
        return 'please confirm the quantity'
    if item.quantity_unit is None or unit is None:
        return 'please confirm the quantity unit'
    return f'please confirm how many {unit}s are in each {item.quantity_unit}'


def _rationale(quote: Quote) -> str:
    '''Customer-facing explanation of the price and discount.'''
    parts = []
    if quote.lines:
        parts.append(
            'Prices are our standard list prices per sheet, piece or roll.'
        )
        if quote.discount_rate:
            parts.append(
                f'Your subtotal of ${quote.subtotal:,.2f} qualifies for a '
                f'{quote.discount_rate:.0%} bulk discount, saving '
                f'${quote.discount_amount:,.2f}.'
            )
        next_tier = min(
            (tier for tier in DISCOUNT_TIERS if tier[0] > quote.subtotal),
            default=None,
        )
        if next_tier:
            parts.append(
                f'Orders of ${next_tier[0]:,.0f} or more receive a '
                f'{next_tier[1]:.0%} bulk discount.'
            )
        parts.append(f'Total: ${quote.total:,.2f}.')
    parts.extend(
        f'Not yet priced: {item.customer_description} ({item.reason}).'
        for item in quote.unpriced
    )
    return ' '.join(parts)


def price_quote(parsed: ParsedItems | dict) -> Quote:
    '''Price every matched item with a known quantity; list the rest as unpriced.

    Repeated lines for one product are combined in catalog units.
    '''
    parsed = ParsedItems.model_validate(parsed)
    quantities: dict[str, int] = {}
    costs: dict[str, float] = {}
    units: dict[str, str] = {}
    unpriced = []

    for item in parsed.items:
        unit = None
        quantity = None
        if item.match_status == 'matched':
            name = item.item_name.value
            unit = catalog_unit(name, item.category.value)
            quantity = convert_quantity(
                item.units, item.quantity_unit, unit,
                item.package_size, item.package_unit,
            )
        if quantity is None or not quantity.is_integer():
            unpriced.append(UnpricedItem(
                customer_description=item.customer_description,
                reason=_unpriced_reason(item, unit),
            ))
            continue
        quantities[name] = quantities.get(name, 0) + int(quantity)
        costs[name] = item.unit_price
        units[name] = unit

    list_prices = {
        name: round(costs[name] * (1 + MARKUP), 4) for name in quantities
    }
    list_totals = {
        name: _money(quantity * list_prices[name])
        for name, quantity in quantities.items()
    }
    subtotal = _money(sum(list_totals.values()))
    rate = discount_rate(subtotal)
    lines = [
        QuoteLine(
            item_name=name,
            quantity=quantity,
            unit=units[name],
            unit_price=list_prices[name],
            list_total=list_totals[name],
            sale_price=_money(list_totals[name] * (1 - rate)),
        )
        for name, quantity in quantities.items()
    ]
    total = _money(sum(line.sale_price for line in lines))
    cost = _money(sum(
        quantity * costs[name] for name, quantity in quantities.items()
    ))
    quote = Quote(
        lines=lines,
        unpriced=unpriced,
        subtotal=subtotal,
        discount_rate=rate,
        discount_amount=_money(subtotal - total),
        total=total,
        rationale='',
        cost=cost,
        gross_margin=round((total - cost) / total, 4) if total else None,
    )
    quote.rationale = _rationale(quote)
    return quote
