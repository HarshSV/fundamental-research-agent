import json

def calculate_pead_score(quarterly_data):
    """
    Calculates the Post-Earnings Announcement Drift (PEAD) score based on fundamental quarterly data.
    
    Expected keys in quarterly_data:
    - net_profit_growth_yoy (float: percentage, e.g., 45.0 for 45%)
    - revenue_growth_yoy (float: percentage, e.g., 20.0 for 20%)
    - op_margin_current (float)
    - op_margin_yoy (float)
    """
    score = 0
    
    # +40 points if net profit growth yoy is > 40%
    if quarterly_data.get('net_profit_growth_yoy', 0) > 40:
        score += 40
        
    # +30 points if revenue growth yoy is > 15%
    if quarterly_data.get('revenue_growth_yoy', 0) > 15:
        score += 30
        
    # +30 points if current quarter's operating margin has expanded compared to the same quarter last year
    op_margin_curr = quarterly_data.get('op_margin_current', 0)
    op_margin_yoy = quarterly_data.get('op_margin_yoy', 0)
    
    if op_margin_curr > op_margin_yoy:
        score += 30
        
    # Determine the action tag based on total score
    if score >= 70:
        action_tag = 'HIGH CONVICTION'
    elif score >= 40:
        action_tag = 'WATCHLIST'
    else:
        action_tag = 'REJECT'
        
    return {
        'pead_score': score,
        'action_tag': action_tag
    }

if __name__ == '__main__':
    # Dummy data testing block
    dummy_data = {
        'net_profit_growth_yoy': 45.5,   # > 40% (+40 pts)
        'revenue_growth_yoy': 12.0,      # < 15% (+0 pts)
        'op_margin_current': 18.5,       
        'op_margin_yoy': 15.0            # Expanded (+30 pts)
    }
    
    # Expected score for dummy data: 40 + 0 + 30 = 70 (HIGH CONVICTION)
    result = calculate_pead_score(dummy_data)
    
    print("Testing PEAD Score Engine with Dummy Data:")
    print(json.dumps(dummy_data, indent=4))
    print("\nResult:")
    print(json.dumps(result, indent=4))
