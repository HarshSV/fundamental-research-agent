import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

class StockReportGenerator:
    """
    Generates professional PDF fundamental research reports for stock symbols
    using metrics from the LangGraph state.
    """
    
    @staticmethod
    def format_currency(val):
        if val is None or val == "":
            return "N/A"
        try:
            num = float(val)
            if abs(num) >= 10000000:
                return f"Rs. {num / 10000000:.2f} Cr"
            elif abs(num) >= 100000:
                return f"Rs. {num / 100000:.2f} L"
            return f"Rs. {num:,.2f}"
        except:
            return str(val)

    @staticmethod
    def format_percent(val):
        if val is None or val == "":
            return "N/A"
        try:
            num = float(val)
            # check if it is a small decimal fraction or already formatted
            if abs(num) <= 1.0 and num != 0.0:
                return f"{num * 100:.2f}%"
            return f"{num:.2f}%"
        except:
            return str(val)

    @staticmethod
    def format_num(val):
        if val is None or val == "":
            return "N/A"
        try:
            return f"{float(val):.2f}"
        except:
            return str(val)

    @classmethod
    def build_pdf_report(cls, state_data: dict, output_path):
        """
        Builds a multi-page PDF report document and saves it to output_path (string or file-like object).
        Compiles all 20 fundamental metrics cleanly without feature codes.
        """
        # Ensure exports directory exists if output_path is a file path string
        if isinstance(output_path, str):
            dir_name = os.path.dirname(os.path.abspath(output_path))
            os.makedirs(dir_name, exist_ok=True)
        
        symbol = state_data.get('symbol', 'UNKNOWN')
        business_score = state_data.get('business_score', 0)
        verdict = state_data.get('verdict', 'PENDING')
        peer_synthesis = state_data.get('peer_synthesis_data', {}) or {}
        calculated_metrics = state_data.get('calculated_metrics', {}) or {}
        qualitative_data = state_data.get('qualitative_analysis', {}) or {}
        parsed_json = qualitative_data.get('parsed_json', {}) or {}
        
        company_name = calculated_metrics.get('company_name') or symbol
        
        # Initialize Document
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=45,
            leftMargin=45,
            topMargin=45,
            bottomMargin=45
        )
        
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            name='ReportTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=20,
            leading=24,
            textColor=colors.HexColor('#1A365D'),
            spaceAfter=5
        )
        
        subtitle_style = ParagraphStyle(
            name='ReportSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=11,
            leading=14,
            textColor=colors.HexColor('#4A5568'),
            spaceAfter=15
        )
        
        section_style = ParagraphStyle(
            name='ReportSection',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#2C5282'),
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True
        )
        
        body_style = ParagraphStyle(
            name='ReportBody',
            parent=styles['BodyText'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#2D3748')
        )

        body_bold_style = ParagraphStyle(
            name='ReportBodyBold',
            parent=styles['BodyText'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#1A202C')
        )
        
        table_header_style = ParagraphStyle(
            name='TableHeader',
            parent=styles['BodyText'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=11,
            textColor=colors.white
        )
        
        story = []
        
        # --- PAGE 1: TITLE & EXECUTIVE SUMMARY & HISTORICAL statements ---
        story.append(Paragraph(f"{company_name} ({symbol})", title_style))
        story.append(Paragraph("Comprehensive Fundamental Equity Research Report", subtitle_style))
        
        story.append(Paragraph("Executive Summary & Core Parameters", section_style))
        
        val_metrics = calculated_metrics.get('F-03_Valuation_Metrics', {}) or {}
        solvency = calculated_metrics.get('F-08_Solvency_Metrics', {}) or {}
        
        # Format tags
        tags = peer_synthesis.get('comparative_tags', [])
        tags_str = ", ".join(tags) if tags else "None"
        
        summary_data = [
            [Paragraph("Metric Parameter", table_header_style), Paragraph("Value", table_header_style), Paragraph("Metric Parameter", table_header_style), Paragraph("Value", table_header_style)],
            [Paragraph("Ticker symbol", body_style), Paragraph(symbol, body_bold_style), Paragraph("Business Quality Score", body_style), Paragraph(f"{business_score} / 100", body_bold_style)],
            [Paragraph("Safety Gate status", body_style), Paragraph(verdict, body_bold_style), Paragraph("Sector median tags", body_style), Paragraph(tags_str, body_bold_style)],
            [Paragraph("Last Traded Price", body_style), Paragraph(cls.format_currency(val_metrics.get('last_price')), body_style), Paragraph("Market Capitalization", body_style), Paragraph(cls.format_currency(val_metrics.get('MarketCap')), body_style)],
            [Paragraph("Trailing P/E ratio", body_style), Paragraph(cls.format_num(val_metrics.get('PE')), body_style), Paragraph("Price-to-Book (P/B)", body_style), Paragraph(cls.format_num(val_metrics.get('PB')), body_style)],
            [Paragraph("EV/EBITDA multiple", body_style), Paragraph(cls.format_num(val_metrics.get('EV_EBITDA')), body_style), Paragraph("Free Cash Flow Yield", body_style), Paragraph(cls.format_percent(val_metrics.get('FCF_Yield')), body_style)],
            [Paragraph("Shares Outstanding", body_style), Paragraph(cls.format_num(val_metrics.get('SharesOutstanding')), body_style), Paragraph("Total Debt", body_style), Paragraph(cls.format_currency(solvency.get('total_debt')), body_style)]
        ]
        
        summary_table = Table(summary_data, colWidths=[120, 130, 130, 140])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#1A365D')),
            ('BACKGROUND', (2, 0), (3, 0), colors.HexColor('#1A365D')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 10))
        
        # Financial Statements (F-01)
        story.append(Paragraph("Historical Financial Statements (5-Year Series)", section_style))
        
        f01 = calculated_metrics.get('F-01_Financial_Statements', {}) or {}
        annual_f01 = f01.get('annual', {}) or {}
        inc_grid = annual_f01.get('income_stmt', {}) or {}
        
        dates_sorted = sorted(inc_grid.keys(), reverse=True)
        if dates_sorted:
            # We will show: Total Revenue, Gross Profit, EBITDA, Operating Income, Net Income
            row_keys = ["Total Revenue", "Gross Profit", "EBITDA", "Operating Income", "Net Income"]
            fin_headers = [Paragraph("Line Item (Annual)", table_header_style)] + [Paragraph(d, table_header_style) for d in dates_sorted]
            fin_data = [fin_headers]
            for rk in row_keys:
                row_cells = [Paragraph(rk, body_style)]
                for d in dates_sorted:
                    # Search key case-insensitively
                    grid_val = None
                    for k in inc_grid[d].keys():
                        if rk.lower() in k.lower():
                            grid_val = inc_grid[d][k]
                            break
                    row_cells.append(Paragraph(cls.format_currency(grid_val), body_style))
                fin_data.append(row_cells)
                
            fin_table = Table(fin_data, colWidths=[160] + [70] * len(dates_sorted))
            fin_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(fin_table)
        else:
            story.append(Paragraph("No financial statements series found.", body_style))
            
        story.append(PageBreak())
        
        # --- PAGE 2: RATIOS, MARGINS, GROWTH & COMMENTARY ---
        story.append(Paragraph("Core Return & Efficiency Ratios", section_style))
        ratios_list = calculated_metrics.get('F-02_Ratio_Analysis', []) or []
        if ratios_list:
            ratio_headers = [
                Paragraph("Period", table_header_style),
                Paragraph("ROE", table_header_style),
                Paragraph("ROCE", table_header_style),
                Paragraph("EBITDA Margin", table_header_style),
                Paragraph("Asset Turnover", table_header_style)
            ]
            ratio_data = [ratio_headers]
            for r in ratios_list:
                ratio_data.append([
                    Paragraph(r.get('date', 'N/A'), body_style),
                    Paragraph(cls.format_percent(r.get('ROE')), body_style),
                    Paragraph(cls.format_percent(r.get('ROCE')), body_style),
                    Paragraph(cls.format_percent(r.get('EBITDA_Margin')), body_style),
                    Paragraph(f"{cls.format_num(r.get('Asset_Turnover'))}x", body_style),
                ])
            ratio_table = Table(ratio_data, colWidths=[100] * 5)
            ratio_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(ratio_table)
        else:
            story.append(Paragraph("No ratio matrix computed.", body_style))
            
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("Margin Audit & Growth CAGRs", section_style))
        margin_obj = calculated_metrics.get('F-06_Margin_Analysis', {}) or {}
        margins_annual = margin_obj.get('margins_annual', []) or []
        growth_summary = calculated_metrics.get('F-05_Growth_Summary', {}) or {}
        
        col_w = [85, 85, 85, 85, 85, 95]
        margin_headers = [
            Paragraph("Period", table_header_style),
            Paragraph("Gross Margin", table_header_style),
            Paragraph("EBITDA Margin", table_header_style),
            Paragraph("EBIT Margin", table_header_style),
            Paragraph("PAT Margin", table_header_style),
            Paragraph("Audit Status", table_header_style)
        ]
        margin_data = [margin_headers]
        tag = margin_obj.get('margin_status_tag', 'STABLE')
        for idx, m in enumerate(margins_annual):
            margin_data.append([
                Paragraph(m.get('date', 'N/A'), body_style),
                Paragraph(cls.format_percent(m.get('gross_margin')), body_style),
                Paragraph(cls.format_percent(m.get('ebitda_margin')), body_style),
                Paragraph(cls.format_percent(m.get('ebit_margin')), body_style),
                Paragraph(cls.format_percent(m.get('pat_margin')), body_style),
                Paragraph(tag if idx == len(margins_annual) - 1 else "", body_bold_style)
            ])
        margin_table = Table(margin_data, colWidths=col_w)
        margin_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(margin_table)
        
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>3-Year CAGR Revenue Growth:</b> {cls.format_percent(growth_summary.get('cagr_3y_revenue'))} | <b>3-Year CAGR PAT Growth:</b> {cls.format_percent(growth_summary.get('cagr_3y_pat'))}", body_style))
        vel = growth_summary.get('growth_velocity_tag')
        if vel:
            story.append(Paragraph(f"<b>Growth Velocity:</b> {vel}", body_style))
        story.append(Spacer(1, 10))

        # F-13: Latest-quarter results signal (beat / miss + PEAD action tag)
        results_signal = calculated_metrics.get('F-13_Results_Signal', {}) or {}
        if results_signal:
            story.append(Paragraph("Latest Quarterly Results Signal", section_style))
            bm = results_signal.get('beat_miss', 'INLINE')
            bm_color = {"BEAT": "green", "MISS": "red"}.get(bm, "#B7791F")
            rs_rows = [
                [Paragraph("Results Parameter", table_header_style), Paragraph("Reading", table_header_style)],
                [Paragraph("Latest Quarter", body_style), Paragraph(str(results_signal.get('latest_quarter', 'N/A')), body_bold_style)],
                [Paragraph("Earnings Verdict", body_style), Paragraph(f"<font color='{bm_color}'><b>{bm}</b></font>", body_style)],
                [Paragraph("Conviction (PEAD action)", body_style), Paragraph(f"{results_signal.get('action_tag', 'N/A')} (score {results_signal.get('pead_score', 0)})", body_bold_style)],
                [Paragraph("Revenue YoY", body_style), Paragraph(cls.format_percent(results_signal.get('revenue_yoy')), body_style)],
                [Paragraph("PAT YoY", body_style), Paragraph(cls.format_percent(results_signal.get('pat_yoy')), body_style)],
            ]
            rs_table = Table(rs_rows, colWidths=[200, 320])
            rs_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(rs_table)
            story.append(Spacer(1, 10))
        
        # Capital Efficiency Commentary
        story.append(Paragraph("Capital Efficiency Commentary (ROE/ROCE AI Audit)", section_style))
        f07_commentary = parsed_json.get('F-07', {}).get('commentary', 'The ROE and ROCE multiples trace operational cycles, reflecting corporate capital efficiency and reinvestment structures.')
        story.append(Paragraph(f07_commentary, body_style))
        
        story.append(PageBreak())
        
        # --- PAGE 3: VALUATION, DCF, SOLVENCY & CASH CONVERSION ---
        story.append(Paragraph("Intrinsic Value Scenarios & Reverse DCF Sensitivity", section_style))
        
        dcf_data = calculated_metrics.get('F-18_Reverse_DCF', {}) or {}
        scenarios = dcf_data.get('scenarios', {}) or {}
        
        scen_rows = [
            [Paragraph("Scenario Case", table_header_style), Paragraph("Implied Value Per Share", table_header_style)],
            [Paragraph("Bear Case (5% growth path)", body_style), Paragraph(cls.format_currency(scenarios.get('Bear_Value')), body_bold_style)],
            [Paragraph("Base Case (10% growth path)", body_style), Paragraph(cls.format_currency(scenarios.get('Base_Value')), body_bold_style)],
            [Paragraph("Bull Case (15% growth path)", body_style), Paragraph(cls.format_currency(scenarios.get('Bull_Value')), body_bold_style)]
        ]
        scen_table = Table(scen_rows, colWidths=[200, 320])
        scen_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A365D')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(scen_table)
        story.append(Spacer(1, 10))
        
        # Sensitivity matrix
        matrix = dcf_data.get('sensitivity_matrix', {}) or {}
        disc_rates = sorted(list(matrix.keys()))
        if disc_rates:
            grow_rates = sorted(list(matrix[disc_rates[0]].keys()))
            sens_headers = [Paragraph("Disc \\ Growth", table_header_style)] + [Paragraph(g, table_header_style) for g in grow_rates]
            sens_rows = [sens_headers]
            for dr in disc_rates:
                row_cells = [Paragraph(dr, body_bold_style)]
                for gr in grow_rates:
                    row_cells.append(Paragraph(cls.format_currency(matrix[dr][gr]), body_style))
                sens_rows.append(row_cells)
                
            sens_table = Table(sens_rows, colWidths=[100] + [84] * len(grow_rates))
            sens_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 1), (0, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(sens_table)
        else:
            story.append(Paragraph("Sensitivity matrix details not calculated.", body_style))
            
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("Solvency, Debt Limits & Cash Flow Quality", section_style))
        cf_conv = calculated_metrics.get('F-09_Cash_Flow_Conversion', {}) or {}
        
        solv_data = [
            [Paragraph("Solvency Parameters", table_header_style), Paragraph("Computed Leverage Ratio", table_header_style), Paragraph("Cash Flow conversion Metrics", table_header_style), Paragraph("Computed Cash ratio", table_header_style)],
            [Paragraph("Debt to Equity Ratio", body_style), Paragraph(f"{cls.format_num(solvency.get('debt_to_equity'))}x", body_style), Paragraph("Operating Cash Flow (CFO)", body_style), Paragraph(cls.format_currency(cf_conv.get('CFO')), body_style)],
            [Paragraph("Net Debt / EBITDA", body_style), Paragraph(f"{cls.format_num(solvency.get('net_debt_to_ebitda'))}x", body_style), Paragraph("Capital Expenditures (Capex)", body_style), Paragraph(cls.format_currency(cf_conv.get('Capex')), body_style)],
            [Paragraph("Interest Coverage ratio", body_style), Paragraph(f"{cls.format_num(solvency.get('interest_coverage'))}x", body_style), Paragraph("Free Cash Flow (FCF)", body_style), Paragraph(cls.format_currency(cf_conv.get('FCF')), body_bold_style)],
            [Paragraph("Total Debt Outstanding", body_style), Paragraph(cls.format_currency(solvency.get('total_debt')), body_style), Paragraph("CFO-to-PAT Conversion", body_style), Paragraph(f"{cls.format_num(cf_conv.get('CFO_to_PAT'))}x", body_bold_style)]
        ]
        solv_table = Table(solv_data, colWidths=[130, 120, 150, 120])
        solv_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#2C5282')),
            ('BACKGROUND', (2, 0), (3, 0), colors.HexColor('#2C5282')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(solv_table)
        
        story.append(PageBreak())
        
        # --- PAGE 4: OWNERSHIP, BENCHMARKS, PEER MATRIX ---
        story.append(Paragraph("Ownership, Promoter Pledge & Institutional Flows", section_style))
        own = calculated_metrics.get('F-10_F-11_F-12_Ownership', {}) or {}

        # Provenance line: real NSE filing vs fallback, with the as-of quarter
        own_source = own.get('data_source', 'fallback')
        as_of = own.get('as_of_quarter')
        if own_source == 'NSE' and as_of:
            prov = f"<b>Source:</b> NSE corporate filings &nbsp;|&nbsp; <b>Shareholding as of:</b> {as_of}"
        else:
            prov = "<b>Source:</b> Fallback estimate (NSE filing not yet available for this symbol)."
        story.append(Paragraph(prov, body_style))
        story.append(Spacer(1, 6))

        own_rows = [
            [Paragraph("Shareholding Category", table_header_style), Paragraph("Percentage Stake", table_header_style)],
            [Paragraph("Promoter Stake", body_style), Paragraph(cls.format_percent(own.get('promoter_stake')), body_style)],
            [Paragraph("Promoter Pledge (as % of promoter holding)", body_style), Paragraph(cls.format_percent(own.get('promoter_pledge_of_stake')), body_bold_style)],
            [Paragraph("FII &amp; DII Institutional Stake", body_style), Paragraph(cls.format_percent(own.get('fii_dii_stake')), body_style)],
            [Paragraph("Public Float Stake", body_style), Paragraph(cls.format_percent(own.get('public_stake')), body_style)]
        ]
        own_table = Table(own_rows, colWidths=[200, 320])
        own_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A365D')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(own_table)
        story.append(Spacer(1, 10))

        # F-12: real market-wide FII/DII net flows (latest session)
        story.append(Paragraph("Institutional Fund Flows (Market-Wide, Latest Session)", section_style))
        market = own.get('market_fii_dii', []) or []
        if market:
            flow_date = market[0].get('date', '')
            flow_headers = [
                Paragraph("Participant", table_header_style),
                Paragraph("Gross Buy (Rs Cr)", table_header_style),
                Paragraph("Gross Sell (Rs Cr)", table_header_style),
                Paragraph("Net (Rs Cr)", table_header_style)
            ]
            flow_rows = [flow_headers]
            for fl in market:
                net = fl.get('net_cr')
                net_color = "green" if (net or 0) > 0 else ("red" if (net or 0) < 0 else "black")
                net_str = f"{net:+,.2f}" if net is not None else "N/A"
                flow_rows.append([
                    Paragraph(fl.get('category', 'N/A'), body_bold_style),
                    Paragraph(cls.format_num(fl.get('buy_cr')), body_style),
                    Paragraph(cls.format_num(fl.get('sell_cr')), body_style),
                    Paragraph(f"<font color='{net_color}'><b>{net_str}</b></font>", body_style),
                ])
            flow_table = Table(flow_rows, colWidths=[130] * 4)
            flow_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(flow_table)
            if flow_date:
                story.append(Spacer(1, 4))
                story.append(Paragraph(f"<i>NSE FII/DII trade data for {flow_date}. Per-stock quarter-over-quarter holding deltas require a multi-quarter feed (paid provider).</i>", body_style))
        else:
            story.append(Paragraph("Live FII/DII market flow data is currently unavailable.", body_style))

        story.append(Spacer(1, 10))
        
        story.append(Paragraph("Sector Peer Comparison Matrix", section_style))
        peer_headers = [
            Paragraph("Symbol", table_header_style),
            Paragraph("Price (INR)", table_header_style),
            Paragraph("P/E Ratio", table_header_style),
            Paragraph("Operating Margin", table_header_style),
            Paragraph("ROE %", table_header_style)
        ]
        peer_data = [peer_headers]
        
        # Add target
        target = peer_synthesis.get('target_metrics', {}) or {}
        peer_data.append([
            Paragraph(f"<b>{symbol} (Target)</b>", body_bold_style),
            Paragraph(cls.format_currency(target.get('lastPrice')), body_style),
            Paragraph(cls.format_num(target.get('pe')), body_style),
            Paragraph(cls.format_percent(target.get('operatingMargin')), body_style),
            Paragraph(cls.format_percent(target.get('roe')), body_style)
        ])
        # Add peers
        peer_matrix = peer_synthesis.get('peer_matrix', []) or []
        for p in peer_matrix:
            peer_data.append([
                Paragraph(p.get('symbol', 'UNKNOWN'), body_style),
                Paragraph(cls.format_currency(p.get('lastPrice')), body_style),
                Paragraph(cls.format_num(p.get('pe')), body_style),
                Paragraph(cls.format_percent(p.get('operatingMargin')), body_style),
                Paragraph(cls.format_percent(p.get('roe')), body_style)
            ])
        # Add sector average
        avg = peer_synthesis.get('sector_averages', {}) or {}
        peer_data.append([
            Paragraph("<b>Sector Average</b>", body_bold_style),
            Paragraph(cls.format_currency(avg.get('lastPrice')), body_style),
            Paragraph(cls.format_num(avg.get('pe')), body_style),
            Paragraph(cls.format_percent(avg.get('operatingMargin')), body_style),
            Paragraph(cls.format_percent(avg.get('roe')), body_style)
        ])
        
        peer_table = Table(peer_data, colWidths=[100] * 5)
        peer_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A365D')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F7FAFC')]),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#EDF2F7')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(peer_table)
        story.append(Spacer(1, 10))

        # F-17: Sector percentile standing
        benchmark = peer_synthesis.get('sector_benchmark', {}) or {}
        pcts = benchmark.get('percentiles', {}) or {}
        overall_pct = benchmark.get('overall_percentile')
        if overall_pct is not None or any(v is not None for v in pcts.values()):
            story.append(Paragraph("Sector Percentile Standing", section_style))
            if overall_pct is not None:
                story.append(Paragraph(f"<b>Overall sector percentile:</b> {overall_pct}th percentile (higher = better positioned vs peers).", body_bold_style))
                story.append(Spacer(1, 4))
            pct_label = {
                'pe': 'Valuation (P/E)', 'operatingMargin': 'Operating Margin',
                'roe': 'Return on Equity', 'revenueGrowth': 'Revenue Growth',
                'debtToEquity': 'Balance Sheet (D/E)'
            }
            pct_headers = [Paragraph("Metric", table_header_style), Paragraph("Percentile vs Sector", table_header_style)]
            pct_rows = [pct_headers]
            for key, label in pct_label.items():
                v = pcts.get(key)
                if v is None:
                    continue
                v_color = "green" if v >= 60 else ("red" if v < 40 else "black")
                pct_rows.append([
                    Paragraph(label, body_style),
                    Paragraph(f"<font color='{v_color}'><b>{v}th</b></font>", body_style),
                ])
            if len(pct_rows) > 1:
                pct_table = Table(pct_rows, colWidths=[260, 260])
                pct_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]))
                story.append(pct_table)

        story.append(PageBreak())

        # --- PAGE 5: AI AUDITS: GOVERNANCE, FORENSICS & MOATS ---
        story.append(Paragraph("Strategic Corporate Governance Summary", section_style))
        f14_gov = parsed_json.get('F-14', {}) or {}
        story.append(Paragraph(f"<b>Corporate Governance score:</b> {f14_gov.get('governance_score', 80)}/100", body_bold_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Auditor comments:</b> {f14_gov.get('auditor_remarks', 'Clean independent review.')}", body_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Regulatory or Legal proceedings:</b> {f14_gov.get('legal_issues', 'None material.')}", body_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>Key Observations & Governance Remarks:</b>", body_bold_style))
        for obs in f14_gov.get('key_remarks', []):
            story.append(Paragraph(f"- {obs}", body_style))
            
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("Forensic Accounting Assessment Checklist", section_style))
        f16_foren = parsed_json.get('F-16', {}) or {}
        story.append(Paragraph(f"<b>Forensic Risk level:</b> {f16_foren.get('risk_level', 'Low Risk')}", body_bold_style))
        story.append(Spacer(1, 5))
        
        foren_headers = [
            Paragraph("Audited Checklist test name", table_header_style),
            Paragraph("Status", table_header_style),
            Paragraph("Severity", table_header_style),
            Paragraph("Forensics Detail Notes", table_header_style)
        ]
        foren_rows = [foren_headers]
        checks = f16_foren.get('checks', []) or []
        for chk in checks:
            stat_color = "green" if chk.get('status') == 'PASS' else "red"
            foren_rows.append([
                Paragraph(chk.get('name', 'N/A'), body_bold_style),
                Paragraph(f"<font color='{stat_color}'><b>{chk.get('status')}</b></font>", body_style),
                Paragraph(f"{chk.get('severity', 0)}/10", body_style),
                Paragraph(chk.get('details', 'No flags raised.'), body_style),
            ])
            
        foren_table = Table(foren_rows, colWidths=[150, 60, 60, 250])
        foren_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C5282')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(foren_table)
        
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("Competitive Moat Audit & Barriers Assessment", section_style))
        f20_moat = parsed_json.get('F-20', {}) or {}
        
        _mscore = f20_moat.get('moat_score')
        moat_rows = [
            [Paragraph("Moat Strengths Parameters", table_header_style), Paragraph("Computed Assessment Status", table_header_style)],
            [Paragraph("Business Moat Classification", body_style), Paragraph(f"<b>{f20_moat.get('moat_strength', 'Narrow')} Moat</b>", body_bold_style)],
        ]
        if _mscore is not None:
            moat_rows.append([Paragraph("Moat Score (data-driven)", body_style), Paragraph(f"<b>{_mscore} / 100</b>", body_bold_style)])
        moat_rows += [
            [Paragraph("Moat confidence percentage", body_style), Paragraph(cls.format_percent(f20_moat.get('confidence_level')), body_style)],
            [Paragraph("Pricing Power score", body_style), Paragraph(f"{f20_moat.get('pricing_power', 5.0):.1f} / 10.0", body_style)],
            [Paragraph("Barriers to market Entry score", body_style), Paragraph(f"{f20_moat.get('barriers_to_entry', 5.0):.1f} / 10.0", body_style)]
        ]
        moat_table = Table(moat_rows, colWidths=[200, 320])
        moat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A365D')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(moat_table)
        story.append(Spacer(1, 6))

        # Computed moat signals / risks (data-driven).
        for _lbl, _items in [("Moat Signals:", f20_moat.get('signals') or []),
                             ("Moat Risks:", f20_moat.get('warnings') or [])]:
            if _items:
                story.append(Paragraph(f"<b>{_lbl}</b>", body_bold_style))
                for _it in _items[:5]:
                    story.append(Paragraph(f"•  {_it}", body_style))
                story.append(Spacer(1, 4))

        story.append(Paragraph("<b>Barriers & Moat Narrative Memo:</b>", body_bold_style))
        story.append(Paragraph(f20_moat.get('memo_text', 'No moat assessment memo text generated.'), body_style))
        
        # Build document
        doc.build(story)
        if isinstance(output_path, str):
            print(f"[StockReportGenerator] Successfully compiled and saved PDF report to: {output_path}")
        else:
            print("[StockReportGenerator] Successfully compiled PDF report in-memory")

if __name__ == '__main__':
    # Local verification run
    dummy_state = {
        'symbol': 'INFY',
        'business_score': 85,
        'verdict': 'STRUCTURAL_ANALYSIS_COMPLETE',
        'qualitative_analysis': {
            'parsed_json': {
                'F-07': {'commentary': 'Capital efficiency ROE vs ROCE details.'},
                'F-14': {
                    'governance_score': 85,
                    'key_remarks': ['Governance complies with standards.', 'Professional board leadership.'],
                    'auditor_remarks': 'Unqualified audit reports.',
                    'legal_issues': 'None reported.'
                },
                'F-15': {
                    'bull': {'revenue_growth': 14.5, 'drivers': 'Export demand.', 'risks': 'Margin pressure'},
                    'base': {'revenue_growth': 9.5, 'drivers': 'Steady market.', 'risks': 'Competition'},
                    'bear': {'revenue_growth': 4.5, 'drivers': 'Rural headwinds.', 'risks': 'Volume pressure'}
                },
                'F-16': {
                    'risk_level': 'Low',
                    'checks': [
                        {'name': 'CFO vs PAT Conversion', 'status': 'PASS', 'severity': 1, 'details': 'Matches perfectly'},
                        {'name': 'Share Dilution Check', 'status': 'PASS', 'severity': 0, 'details': 'Zero dilution'},
                    ]
                },
                'F-20': {
                    'moat_strength': 'Wide',
                    'confidence_level': 85.0,
                    'pricing_power': 8.0,
                    'barriers_to_entry': 9.0,
                    'memo_text': 'Brand equity switching barrier.'
                }
            }
        },
        'peer_synthesis_data': {
            'target_metrics': {'symbol': 'INFY', 'lastPrice': 1600.0, 'pe': 25.0, 'operatingMargin': 0.21, 'roe': 0.32},
            'peer_matrix': [
                {'symbol': 'TCS', 'lastPrice': 3800.0, 'pe': 28.0, 'operatingMargin': 0.24, 'roe': 0.45},
                {'symbol': 'WIPRO', 'lastPrice': 450.0, 'pe': 20.0, 'operatingMargin': 0.16, 'roe': 0.18}
            ],
            'sector_averages': {'lastPrice': 1950.0, 'pe': 24.3, 'operatingMargin': 0.20, 'roe': 0.316},
            'comparative_tags': ['OUTPERFORMING']
        },
        'calculated_metrics': {
            'company_name': 'Infosys Limited',
            'F-03_Valuation_Metrics': {
                'last_price': 1600.0,
                'PE': 25.0,
                'PB': 8.5,
                'PS': 5.2,
                'EV_EBITDA': 18.0,
                'FCF_Yield': 0.045,
                'MarketCap': 660000000000,
                'SharesOutstanding': 415000000
            },
            'F-08_Solvency_Metrics': {
                'total_debt': 8000000000,
                'debt_to_equity': 0.1,
                'net_debt_to_ebitda': 0.05,
                'interest_coverage': 45.0,
                'cash_equivalents': 15000000000
            },
            'F-09_Cash_Flow_Conversion': {
                'CFO': 220000000000,
                'Capex': 25000000000,
                'FCF': 195000000000,
                'CFO_to_PAT': 1.1
            },
            'F-10_F-11_F-12_Ownership': {
                'promoter_stake': 15.0,
                'promoter_pledge_of_stake': 0.0,
                'fii_dii_stake': 55.0,
                'public_stake': 30.0,
                'fund_flows': [
                    {'quarter': 'Q1 2026', 'promoter_change': 0.0, 'fii_change': 0.5, 'dii_change': -0.2}
                ]
            }
        }
    }
    
    output_test = 'exports/INFY_test_report.pdf'
    print("Testing StockReportGenerator...")
    StockReportGenerator.build_pdf_report(dummy_state, output_test)
    if os.path.exists(output_test):
        print(f"File verified on disk: {output_test}")
