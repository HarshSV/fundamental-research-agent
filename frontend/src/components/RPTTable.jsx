import React from 'react';

const { useState, useMemo } = React;

/*
 * C.3 — Related-party transactions (RPTs). A plain sortable table, not a
 * bar/line chart: this row's underlying data is a list of counterparty x
 * transaction-type x amount records with a verbatim source quote per row,
 * not a trend or a composition split, so it doesn't fit this codebase's
 * existing donut/bar/spectrum/trend chart components. Amount is numeric
 * and the most useful sort key for an analyst scanning for the largest
 * exposures, so sorting defaults to amount (descending) with a toggle for
 * any column. Each row's quote is collapsed by default (these can be long
 * table-row excerpts) and expands on click for source traceability — same
 * "prove it's real, don't just assert it" spirit as SourcesFooter.
 *
 * `chart` shape (from agent/stock_agent.py's C.3 subpoint builder):
 *   { type: 'rpt_table', frequency: 'None'|'Occasional'|'Frequent'|null,
 *     rows: [{ counterparty, relationship_type, transaction_type,
 *              amount_cr, quote, fiscal_year }] }
 * Every row already passed tools/rpt_extractor.py's verbatim-quote +
 * numeric-anchor guardrail — nothing here is a bare LLM assertion.
 */

const FREQUENCY_STYLE = {
    Frequent: 'text-amber-200 bg-amber-950 border-amber-500/60',
    Occasional: 'text-blue-200 bg-blue-950 border-blue-500/60',
    None: 'text-slate-300 bg-slate-800 border-slate-500/60',
};

const SORT_KEYS = {
    amount: (r) => (r.amount_cr == null ? -Infinity : r.amount_cr),
    counterparty: (r) => (r.counterparty || '').toLowerCase(),
    relationship: (r) => (r.relationship_type || '').toLowerCase(),
    transaction: (r) => (r.transaction_type || '').toLowerCase(),
};

const RPTRow = ({ row }) => {
    const [expanded, setExpanded] = useState(false);
    return (
        <>
            <tr className="border-t border-slate-800 hover:bg-slate-900/40">
                <td className="px-3 py-2 text-[12px] text-slate-100 font-semibold align-top">{row.counterparty}</td>
                <td className="px-3 py-2 text-[12px] text-slate-300 align-top">{row.relationship_type || '—'}</td>
                <td className="px-3 py-2 text-[12px] text-slate-300 align-top">{row.transaction_type || '—'}</td>
                <td className="px-3 py-2 text-[12px] text-slate-100 font-semibold text-right align-top whitespace-nowrap">
                    {row.amount_cr != null ? `₹${Number(row.amount_cr).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr` : 'Not disclosed'}
                </td>
                <td className="px-3 py-2 text-right align-top">
                    <button
                        onClick={() => setExpanded((e) => !e)}
                        className="text-[10px] font-bold uppercase tracking-wider text-slate-500 hover:text-slate-200 transition whitespace-nowrap"
                        title="Show the verbatim Annual Report quote this row was extracted from"
                    >
                        {expanded ? 'Hide quote ▴' : 'Quote ▾'}
                    </button>
                </td>
            </tr>
            {expanded && (
                <tr className="bg-slate-950/60 border-t border-slate-800/60">
                    <td colSpan={5} className="px-3 py-2">
                        <p className="text-[11px] text-slate-400 italic leading-relaxed">
                            "{row.quote}"
                            {row.fiscal_year && <span className="text-slate-600 not-italic"> — FY{row.fiscal_year}, Related Party Disclosures note</span>}
                        </p>
                    </td>
                </tr>
            )}
        </>
    );
};

export const RPTTable = ({ chart }) => {
    const rows = chart?.rows || [];
    const [sortKey, setSortKey] = useState('amount');
    const [sortDir, setSortDir] = useState('desc');

    const sorted = useMemo(() => {
        const keyFn = SORT_KEYS[sortKey] || SORT_KEYS.amount;
        const copy = [...rows];
        copy.sort((a, b) => {
            const av = keyFn(a), bv = keyFn(b);
            if (av < bv) return sortDir === 'asc' ? -1 : 1;
            if (av > bv) return sortDir === 'asc' ? 1 : -1;
            return 0;
        });
        return copy;
    }, [rows, sortKey, sortDir]);

    const onSort = (key) => {
        if (key === sortKey) {
            setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
        } else {
            setSortKey(key);
            setSortDir(key === 'amount' ? 'desc' : 'asc');
        }
    };

    const SortHeader = ({ label, k, align = 'left' }) => (
        <th
            className={`px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400 cursor-pointer select-none hover:text-slate-200 ${align === 'right' ? 'text-right' : 'text-left'}`}
            onClick={() => onSort(k)}
        >
            {label}{sortKey === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
        </th>
    );

    if (!rows.length) return null;

    return (
        <div>
            {chart.frequency && (
                <div className="mb-2 flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">RPT frequency</span>
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${FREQUENCY_STYLE[chart.frequency] || FREQUENCY_STYLE.None}`}>
                        {chart.frequency}
                    </span>
                </div>
            )}
            <div className="overflow-x-auto border border-slate-800 rounded-lg">
                <table className="w-full border-collapse">
                    <thead className="bg-slate-900/60">
                        <tr>
                            <SortHeader label="Counterparty" k="counterparty" />
                            <SortHeader label="Relationship" k="relationship" />
                            <SortHeader label="Transaction type" k="transaction" />
                            <SortHeader label="Amount" k="amount" align="right" />
                            <th className="px-3 py-2"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.map((row, i) => (
                            <RPTRow key={`${row.counterparty}-${i}`} row={row} />
                        ))}
                    </tbody>
                </table>
            </div>
            <p className="mt-2 text-[10px] text-slate-600 italic">
                Every row is validated against a verbatim quote from the company's Annual Report (Related Party Disclosures note) — click "Quote" to see the source text.
            </p>
        </div>
    );
};
