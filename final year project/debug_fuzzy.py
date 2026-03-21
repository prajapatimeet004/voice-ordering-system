from rapidfuzz import fuzz, process

menu = [
    "Masala Dosa", "Paneer Tikka", "Butter Chicken", "Chicken Biryani", 
    "Samosa", "Chhole Bhature", "Dal Makhani", "Palak Paneer", 
    "Aloo Gobi", "Naan", "Roti", "Chai", "Coffee", "Tea", "Burger", "Pizza",
    "Gulab Jamun", "Jalebi", "Idli", "Vada", "Uttapam", "Pav Bhaji", "Misal Pav",
    "Dhokla", "Thepla", "Khandvi", "Vada Pav", "Rajma Chawal",
    "Chicken Tikka", "Mutton Rogan Josh", "Fish Curry", "Prawn Curry"
]

test_cases = ["mohan josh", "nan", "burger", "chai", "mutton rogan josh"]

for t in test_cases:
    match, score, idx = process.extractOne(t, menu, scorer=fuzz.token_set_ratio)
    print(f"Match: '{t}' -> '{match}' Score: {score}")
