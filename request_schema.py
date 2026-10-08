import sqlite3
import pandas as pd
from pathlib import Path
from contextlib import closing
from enum import Enum
from datetime import date
from typing import Literal, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator


database_uri = Path(__file__).with_name('munder_difflin.db').as_uri() + '?mode=ro'
with closing(sqlite3.connect(database_uri, uri=True)) as conn:
    paper_supplies = pd.read_sql('select * from paper_supplies', conn)
paper_supplies.set_index('item_name', inplace=True)
paper_supplies = paper_supplies.to_dict(orient='index')


ItemName = Enum(
    'ItemName',
    {
        f'ITEM_{i}': item_name
        for i, item_name in enumerate(paper_supplies)
    },
    type=str
)


ItemCategory = Enum(
    'ItemCategory', 
    {f'CATEGORY_{i}': category
    for i, category in enumerate(
        sorted({
            details['category']
            for details in paper_supplies.values()
        })
    )
    },
    type=str
)

MatchStatus = Literal[
    'matched',
    'not_offered',
    'needs_clarification'
]

Mood = Literal[
    'happy',
    'miserable',
    'pissed off',
    'sad',
    'stressed',
]

class RequestedItem(BaseModel):
    '''One requested product as extracted from the conversation.'''
    model_config = ConfigDict(
        extra='forbid',
        validate_assignment=True,
    )
    customer_description: str
    match_status: MatchStatus
    item_name: ItemName | None # pyright: ignore[reportInvalidTypeForm]
    category: ItemCategory | None # pyright: ignore[reportInvalidTypeForm]
    unit_price: float | None = Field(strict=True, gt=0, allow_inf_nan=False)
    min_stock_level: int | None = Field(strict=True, ge=0)
    # Extracted from the customer's conversation.
    units: int | None = Field(default=None, strict=True, gt=0)
    quantity_unit: str | None = Field(
        min_length=1,
        description=(
            'Explicit counting unit, normalized to singular lowercase, '
            'such as sheet, ream, box, roll, or piece. Null if unstated.'
        ),
    )
    package_size: int | None = Field(
        strict=True,
        gt=0,
        description='Explicit number of contained units per requested package.',
    )
    package_unit: str | None = Field(
        min_length=1,
        description=(
            'Explicit contained unit, normalized to singular lowercase. '
            'Only populated together with package_size.'
        ),
    )
    # Populated or refreshed by the inventory tool.
    current_stock: int | None = Field(default=None, strict=True, ge=0)
    clarification_question: str | None

    @model_validator(mode='after')
    def check_match(self) -> Self:
        '''Keep catalog fields, units and clarification questions consistent.'''
        if (self.package_size is None) != (self.package_unit is None):
            raise ValueError(
                'package_size and package_unit must both be provided or both be null.'
            )
        for field in ('quantity_unit', 'package_unit'):
            value = getattr(self, field)
            if value is not None and (not value.strip() or value != value.strip().lower()):
                raise ValueError(f'{field} must be a non-empty lowercase unit.')
        # Only these fields must match the catalog.
        catalog_fields = (
            self.item_name,
            self.category,
            self.unit_price,
            self.min_stock_level,
        )
        if self.match_status == 'matched':
            if any(value is None for value in catalog_fields):
                raise ValueError(
                    "A matched item requires item_name, category, "
                    "unit_price, and min_stock_level."
                )
            if self.item_name is None or self.category is None:
                raise ValueError("Matched item identity is missing.")
            expected = paper_supplies[self.item_name.value]
            actual = {
                "category": self.category.value,
                "unit_price": self.unit_price,
                "min_stock_level": self.min_stock_level,
            }
            for field, value in actual.items():
                if value != expected[field]:
                    raise ValueError(
                        f"{field} does not match the catalog for "
                        f"{self.item_name.value}: "
                        f"expected {expected[field]!r}, got {value!r}."
                    )
        else:
            if any(value is not None for value in catalog_fields):
                raise ValueError(
                    "item_name, category, unit_price, and min_stock_level "
                    "must all be null unless match_status is matched."
                )
            # Without an identified product, stock cannot be attached to it.
            if self.current_stock is not None:
                raise ValueError(
                    "current_stock must be null unless the item is matched."
                )
        needs_question = (
            self.match_status == 'needs_clarification'
            or (
                self.match_status == 'matched'
                and self.units is None
            )
        )
        if needs_question and (
            not self.clarification_question
            or not self.clarification_question.strip()
        ):
            raise ValueError("A clarification question is required.")
        
        return self


class ParsedItems(BaseModel):
    '''The complete current request: scope, mood, items and deadline.'''
    model_config = ConfigDict(extra='forbid')
    message_scope: Literal[
        'in_scope',
        'out_of_scope',
        'mixed'
    ] = Field(
        description=(
            "Scope of the latest customer message, interpreted using "
            "conversation history. Use in_scope for paper-supply purchasing "
            "and relevant follow-ups; out_of_scope for "
            "unrelated requests; mixed when both are present."
        )
    )
    mood: Mood | None = Field(
        default=None,
        description=(
            'Customer mood inferred from the purchasing conversation '
            'available so far. Only meaningful when message_scope is '
            'in_scope. Return null for other scopes or insufficient evidence.'
        ),
    )
    items: list[RequestedItem] = Field(
        description=(
            "All currently active paper-supply requests from the "
            "conversation, including requested paper products not in our catalog. "
            "Do not include unrelated requests as items. "
            "Preserve existing items during an unrelated interruption."
        )
    )
    delivery_by: date | None
    delivery_date_question: str | None

    @model_validator(mode='after')
    def check_request(self) -> Self:

        '''Mood only for in-scope messages; ask for a missing deadline.'''
        if self.message_scope != 'in_scope' and self.mood is not None:
            raise ValueError(
                'mood must be null unless message_scope is in_scope.'
            )

        if self.message_scope == 'out_of_scope':
            return self
        needs_delivery = any(
            item.match_status in ('matched', 'needs_clarification')
            for item in self.items
        )
        if (
            needs_delivery
            and self.delivery_by is None
            and (
                not self.delivery_date_question
                or not self.delivery_date_question.strip()
            )
        ):
            raise ValueError(
                'A delivery date clarification question is required.'
            )
        return self
