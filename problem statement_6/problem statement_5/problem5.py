from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP


def money(value: Decimal | int | float | str) -> Decimal:
    """Round monetary values to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Product:
    """Catalog item with category, unit price, and optional item-level discount."""
    sku: str
    name: str
    category: str
    unit_price: Decimal
    item_discount_rate: Decimal = Decimal("0.00")  # e.g., Decimal("0.10") for 10%


@dataclass(frozen=True)
class ThresholdDiscountRule:
    """Spend-threshold discount tier applied to eligible cart amount."""
    min_amount: Decimal
    discount_rate: Decimal  # e.g., Decimal("0.08") for 8%
    description: str


@dataclass(frozen=True)
class BillingPolicy:
    """Category tax rates, threshold tiers, and maximum total concession cap."""
    category_tax_rates: dict[str, Decimal]
    default_tax_rate: Decimal = Decimal("0.18")
    threshold_rules: list[ThresholdDiscountRule] = field(default_factory=list)
    max_concession_amount: Decimal | None = None  # None means uncapped


@dataclass
class LineItemSummary:
    """Calculated breakdown for a single cart line item."""
    product: Product
    quantity: int
    raw_amount: Decimal
    item_discount: Decimal
    threshold_discount_share: Decimal
    total_discount: Decimal
    net_taxable_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal


@dataclass
class InvoiceSummary:
    """Complete itemized retail invoice."""
    invoice_id: str
    customer_name: str
    billing_date: str
    lines: list[LineItemSummary]
    raw_subtotal: Decimal
    item_discount_total: Decimal
    threshold_discount_applied: Decimal
    concession_cap_adjustment: Decimal
    total_concession: Decimal
    taxable_subtotal: Decimal
    total_tax: Decimal
    grand_total: Decimal


def calculate_invoice(
    invoice_id: str,
    customer_name: str,
    billing_date: str,
    cart_items: list[tuple[Product, int]],
    policy: BillingPolicy,
) -> InvoiceSummary:
    """
    Compute line-level and invoice-level totals with category taxes,
    threshold discounts, and maximum concession cap enforcement.
    """
    raw_lines: list[dict] = []
    raw_subtotal = Decimal("0.00")
    item_discount_total = Decimal("0.00")

    for product, qty in cart_items:
        if qty <= 0:
            raise ValueError(f"Quantity for {product.sku} must be positive, got {qty}.")
        line_raw = money(Decimal(qty) * product.unit_price)
        line_item_disc = money(line_raw * product.item_discount_rate)
        after_item_disc = money(line_raw - line_item_disc)

        raw_subtotal = money(raw_subtotal + line_raw)
        item_discount_total = money(item_discount_total + line_item_disc)
        raw_lines.append({
            "product": product,
            "qty": qty,
            "raw": line_raw,
            "item_disc": line_item_disc,
            "after_item_disc": after_item_disc,
        })

    after_item_subtotal = money(raw_subtotal - item_discount_total)

    # Select highest qualifying threshold discount tier
    qualified_rules = [
        r for r in policy.threshold_rules if after_item_subtotal >= r.min_amount
    ]
    best_rule = max(qualified_rules, key=lambda r: r.min_amount) if qualified_rules else None
    raw_threshold_disc = (
        money(after_item_subtotal * best_rule.discount_rate) if best_rule else Decimal("0.00")
    )

    # Enforce maximum total concession limit across item + threshold discounts
    uncapped_concession = money(item_discount_total + raw_threshold_disc)
    concession_cap_adjustment = Decimal("0.00")
    if policy.max_concession_amount is not None:
        cap = money(policy.max_concession_amount)
        if uncapped_concession > cap:
            concession_cap_adjustment = money(uncapped_concession - cap)

    final_threshold_disc = money(
        max(Decimal("0.00"), raw_threshold_disc - concession_cap_adjustment)
    )
    total_concession = money(item_discount_total + final_threshold_disc)

    # Distribute threshold discount proportionally across lines based on post-item-discount share
    line_summaries: list[LineItemSummary] = []
    allocated_threshold = Decimal("0.00")
    total_tax = Decimal("0.00")
    taxable_subtotal = Decimal("0.00")
    grand_total = Decimal("0.00")

    for idx, entry in enumerate(raw_lines):
        product: Product = entry["product"]
        after_item: Decimal = entry["after_item_disc"]

        if final_threshold_disc == Decimal("0.00") or after_item_subtotal == Decimal("0.00"):
            line_thresh_disc = Decimal("0.00")
        elif idx == len(raw_lines) - 1:
            line_thresh_disc = money(final_threshold_disc - allocated_threshold)
        else:
            share = after_item / after_item_subtotal
            line_thresh_disc = money(final_threshold_disc * share)
            allocated_threshold = money(allocated_threshold + line_thresh_disc)

        line_total_disc = money(entry["item_disc"] + line_thresh_disc)
        net_taxable = money(max(Decimal("0.00"), entry["raw"] - line_total_disc))
        tax_rate = policy.category_tax_rates.get(product.category, policy.default_tax_rate)
        line_tax = money(net_taxable * tax_rate)
        line_total = money(net_taxable + line_tax)

        taxable_subtotal = money(taxable_subtotal + net_taxable)
        total_tax = money(total_tax + line_tax)
        grand_total = money(grand_total + line_total)

        line_summaries.append(
            LineItemSummary(
                product=product,
                quantity=entry["qty"],
                raw_amount=entry["raw"],
                item_discount=entry["item_disc"],
                threshold_discount_share=line_thresh_disc,
                total_discount=line_total_disc,
                net_taxable_amount=net_taxable,
                tax_rate=tax_rate,
                tax_amount=line_tax,
                line_total=line_total,
            )
        )

    return InvoiceSummary(
        invoice_id=invoice_id,
        customer_name=customer_name,
        billing_date=billing_date,
        lines=line_summaries,
        raw_subtotal=raw_subtotal,
        item_discount_total=item_discount_total,
        threshold_discount_applied=final_threshold_disc,
        concession_cap_adjustment=concession_cap_adjustment,
        total_concession=total_concession,
        taxable_subtotal=taxable_subtotal,
        total_tax=total_tax,
        grand_total=grand_total,
    )


def format_invoice(inv: InvoiceSummary) -> str:
    """Generate a formatted itemized retail invoice."""
    lines = [
        "=" * 92,
        f"{'ITEMIZED RETAIL INVOICE':^92}",
        "=" * 92,
        f"Invoice No : {inv.invoice_id:<22} Date     : {inv.billing_date}",
        f"Customer   : {inv.customer_name}",
        "-" * 92,
        f"{'Item (SKU)':<26} {'Qty':>4} {'Unit':>9} {'Disc.':>9} {'Taxable':>10} {'Tax':>8} {'Total':>10}",
        "-" * 92,
    ]

    for item in inv.lines:
        label = f"{item.product.name} ({item.product.sku})"[:26]
        lines.append(
            f"{label:<26} {item.quantity:>4} {item.product.unit_price:>9,.2f} "
            f"{item.total_discount:>9,.2f} {item.net_taxable_amount:>10,.2f} "
            f"{item.tax_amount:>8,.2f} {item.line_total:>10,.2f}"
        )

    lines.extend([
        "-" * 92,
        f"{'Gross Merchandise Subtotal':<78}: {inv.raw_subtotal:>11,.2f}",
        f"{'Item-Level Discounts':<78}: {-inv.item_discount_total:>11,.2f}",
        f"{'Threshold Discount (After Cap)':<78}: {-inv.threshold_discount_applied:>11,.2f}",
    ])

    if inv.concession_cap_adjustment > Decimal("0.00"):
        lines.append(
            f"{'Max Concession Cap Adjustment':<78}: {inv.concession_cap_adjustment:>11,.2f}"
        )

    lines.extend([
        f"{'TOTAL CONCESSION APPLIED':<78}: {inv.total_concession:>11,.2f}",
        f"{'Net Taxable Subtotal':<78}: {inv.taxable_subtotal:>11,.2f}",
        f"{'Total Category Tax':<78}: {inv.total_tax:>11,.2f}",
        "=" * 92,
        f"{'GRAND TOTAL PAYABLE':<78}: {inv.grand_total:>11,.2f}",
        "=" * 92,
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    policy = BillingPolicy(
        category_tax_rates={
            "GROCERY": Decimal("0.05"),
            "ELECTRONICS": Decimal("0.18"),
            "APPAREL": Decimal("0.12"),
            "BOOKS": Decimal("0.00"),
        },
        default_tax_rate=Decimal("0.18"),
        threshold_rules=[
            ThresholdDiscountRule(Decimal("1000.00"), Decimal("0.05"), "5% off above 1,000"),
            ThresholdDiscountRule(Decimal("3000.00"), Decimal("0.10"), "10% off above 3,000"),
            ThresholdDiscountRule(Decimal("6000.00"), Decimal("0.15"), "15% off above 6,000"),
        ],
        max_concession_amount=Decimal("1200.00"),
    )

    items = [
        (Product("SKU-101", "Basmati Rice 5kg", "GROCERY", Decimal("650.00"), Decimal("0.05")), 2),
        (Product("SKU-204", "Wireless Mouse", "ELECTRONICS", Decimal("1200.00"), Decimal("0.10")), 2),
        (Product("SKU-309", "Cotton Hoodie", "APPAREL", Decimal("1500.00"), Decimal("0.00")), 2),
        (Product("SKU-412", "Python Cookbook", "BOOKS", Decimal("800.00"), Decimal("0.15")), 1),
    ]

    invoice = calculate_invoice(
        invoice_id="INV-2026-0419",
        customer_name="Karthik Reddy",
        billing_date="2026-11-26",
        cart_items=items,
        policy=policy,
    )
    print(format_invoice(invoice))