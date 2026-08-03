import React from 'react';
import { inrCrore, isNum } from '../lib/format.js';

/*
 * Hand-rolled income-statement sankey (Revenue -> Operating profit/Expenses ->
 * PBT/Interest+D&A -> Net profit/Tax), styled after the classic Apple 10-K
 * sankey. No chart library, no LLM — pure arithmetic + SVG, built only from
 * numbers already present in `income_stmt` (F-01, sourced from Screener P&L
 * scrapes), so it never depends on Groq or any AI pipeline.
 */

const GREEN = 'rgb(var(--emerald-500))';
const RED = 'rgb(var(--red-500))';
const SLATE = 'rgb(var(--slate-500))';

function ribbonPath(x1, y1Top, y1Bot, x2, y2Top, y2Bot) {
  const cx = (x1 + x2) / 2;
  return [
    `M${x1},${y1Top}`,
    `C${cx},${y1Top} ${cx},${y2Top} ${x2},${y2Top}`,
    `L${x2},${y2Bot}`,
    `C${cx},${y2Bot} ${cx},${y1Bot} ${x1},${y1Bot}`,
    'Z',
  ].join(' ');
}

function Node({ x, y, w, h, color, label, value, align }) {
  if (h < 0.5) return null;
  const textX = align === 'left' ? x - 10 : x + w + 10;
  const anchor = align === 'left' ? 'end' : 'start';
  return (
    <g>
      <rect x={x} y={y} width={w} height={Math.max(h, 2)} fill={color} rx="1.5" />
      <text x={textX} y={y + h / 2 - 6} textAnchor={anchor} className="fill-slate-200 text-[11px] font-semibold">
        {label}
      </text>
      <text x={textX} y={y + h / 2 + 9} textAnchor={anchor} className="fill-slate-500 text-[10px] nv-num">
        {inrCrore(value)}
      </text>
    </g>
  );
}

export default function IncomeSankey({ incomeStmt, companyName }) {
  const dates = incomeStmt ? Object.keys(incomeStmt).sort() : [];
  const latestDate = dates[dates.length - 1];
  const row = latestDate ? incomeStmt[latestDate] : null;

  const revenue = row ? Number(row['Total Revenue']) : null;
  let ebitda = row && isNum(row['EBITDA']) ? Number(row['EBITDA']) : null;
  let expenses = row && isNum(row['Total Expenses']) ? Number(row['Total Expenses']) : null;
  if (!isNum(ebitda) && isNum(revenue) && isNum(expenses)) ebitda = revenue - expenses;
  if (!isNum(expenses) && isNum(revenue) && isNum(ebitda)) expenses = revenue - ebitda;

  const pretax = row && isNum(row['Pretax Income']) ? Number(row['Pretax Income']) : null;
  const netProfit = row && isNum(row['Net Income']) ? Number(row['Net Income']) : null;

  const canRender = isNum(revenue) && revenue > 0 && isNum(ebitda) && isNum(expenses) && isNum(pretax) && isNum(netProfit);
  if (!canRender) return null;

  const interestDep = Math.max(ebitda - pretax, 0);
  const pretaxClamped = Math.min(Math.max(pretax, 0), ebitda);
  const tax = Math.max(pretaxClamped - Math.max(netProfit, 0), 0);
  const netProfitClamped = Math.max(Math.min(netProfit, pretaxClamped), 0);
  const expensesClamped = Math.max(Math.min(expenses, revenue), 0);
  const ebitdaClamped = Math.max(revenue - expensesClamped, 0);

  const W = 820, H = 300;
  const pad = 24;
  const usableH = H - pad * 2;
  const scale = revenue > 0 ? usableH / revenue : 0;
  const barW = 10;
  const colX = [60, 300, 540, 780];

  const y0 = pad;
  const ebitdaH = ebitdaClamped * scale;
  const expensesH = expensesClamped * scale;
  const pretaxH = pretaxClamped * scale;
  const interestDepH = interestDep * scale;
  const netProfitH = netProfitClamped * scale;
  const taxH = tax * scale;

  const revY = { top: y0, bot: y0 + revenue * scale };
  const ebitdaY = { top: y0, bot: y0 + ebitdaH };
  const expensesY = { top: ebitdaY.bot, bot: ebitdaY.bot + expensesH };
  const pretaxY = { top: y0, bot: y0 + pretaxH };
  const interestDepY = { top: pretaxY.bot, bot: pretaxY.bot + interestDepH };
  const netProfitY = { top: y0, bot: y0 + netProfitH };
  const taxY = { top: netProfitY.bot, bot: netProfitY.bot + taxH };

  const links = [
    { x1: colX[0] + barW, x2: colX[1], y1: revY, y2: ebitdaY, color: GREEN },
    { x1: colX[0] + barW, x2: colX[1], y1: revY, y2: expensesY, color: RED },
    { x1: colX[1] + barW, x2: colX[2], y1: ebitdaY, y2: pretaxY, color: GREEN },
    { x1: colX[1] + barW, x2: colX[2], y1: ebitdaY, y2: interestDepY, color: RED },
    { x1: colX[2] + barW, x2: colX[3], y1: pretaxY, y2: netProfitY, color: GREEN },
    { x1: colX[2] + barW, x2: colX[3], y1: pretaxY, y2: taxY, color: RED },
  ];

  const year = latestDate ? new Date(latestDate).getFullYear() : '';

  return (
    <div className="nv-card p-4">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="nv-h2 text-[15px] text-slate-200">
          {companyName ? `${companyName} ` : ''}Income Statement{year ? ` · FY${year}` : ''}
        </h2>
        <span className="text-[11px] text-slate-500">Revenue → profit &amp; cost flow (latest FY)</span>
      </div>
      <div className="w-full overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className="min-w-[680px]">
          {links.map((l, i) => (
            <path
              key={i}
              d={ribbonPath(l.x1, l.y1.top, l.y1.bot, l.x2, l.y2.top, l.y2.bot)}
              fill={l.color}
              opacity="0.18"
            />
          ))}
          <Node x={colX[0]} y={revY.top} w={barW} h={revY.bot - revY.top} color={SLATE} label="Revenue" value={revenue} align="left" />
          <Node x={colX[1]} y={ebitdaY.top} w={barW} h={ebitdaH} color={GREEN} label="Operating profit" value={ebitdaClamped} align="left" />
          <Node x={colX[1]} y={expensesY.top} w={barW} h={expensesH} color={RED} label="Total expenses" value={expensesClamped} align="left" />
          <Node x={colX[2]} y={pretaxY.top} w={barW} h={pretaxH} color={GREEN} label="Profit before tax" value={pretaxClamped} align="left" />
          <Node x={colX[2]} y={interestDepY.top} w={barW} h={interestDepH} color={RED} label="Interest & D&A" value={interestDep} align="left" />
          <Node x={colX[3]} y={netProfitY.top} w={barW} h={netProfitH} color={GREEN} label="Net profit" value={netProfitClamped} align="right" />
          <Node x={colX[3]} y={taxY.top} w={barW} h={taxH} color={RED} label="Tax" value={tax} align="right" />
        </svg>
      </div>
    </div>
  );
}
