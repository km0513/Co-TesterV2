"""
Migration script to add Model-Based Testing tables
Run this script to add MBT support to your database
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models.mbt_models import StateMachine, MBTTestExecution, MBTTemplate

def migrate():
    """Run the migration"""
    print("🔄 Starting Model-Based Testing migration...")
    
    try:
        with app.app_context():
            # Create tables
            print("📊 Creating MBT tables...")
            db.create_all()
            
            # Verify tables were created
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            mbt_tables = ['state_machine', 'mbt_test_execution', 'mbt_template']
            created = [t for t in mbt_tables if t in tables]
            
            if len(created) == len(mbt_tables):
                print("✅ All MBT tables created successfully!")
                print(f"   Tables: {', '.join(created)}")
                
                # Create sample template
                create_sample_templates()
                
                return True
            else:
                print("⚠️  Some tables may not have been created")
                print(f"   Expected: {mbt_tables}")
                print(f"   Found: {created}")
                return False
                
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_sample_templates():
    """Create sample state machine templates"""
    print("\n📚 Creating sample templates...")
    
    # Template 1: Login Flow
    login_template = {
        "initial": "idle",
        "states": {
            "idle": {
                "on": {
                    "FILL_VALID": "validInput",
                    "FILL_INVALID": "invalidInput"
                },
                "meta": {
                    "test": {
                        "action": "await page.goto('YOUR_LOGIN_URL')",
                        "assertion": "await expect(page.locator('#email')).toBeVisible()"
                    }
                }
            },
            "validInput": {
                "on": {"SUBMIT": "success"},
                "meta": {
                    "test": {
                        "action": "await page.fill('#email', 'valid@example.com'); await page.fill('#password', 'password123');",
                        "assertion": "await expect(page.locator('button[type=\"submit\"]')).toBeEnabled()"
                    }
                }
            },
            "invalidInput": {
                "on": {"SUBMIT": "error"},
                "meta": {
                    "test": {
                        "action": "await page.fill('#email', 'invalid'); await page.fill('#password', '123');",
                        "assertion": "await expect(page.locator('.error-message')).toBeVisible()"
                    }
                }
            },
            "success": {
                "type": "final",
                "meta": {
                    "test": {
                        "action": "await page.click('button[type=\"submit\"]')",
                        "assertion": "await expect(page).toHaveURL(/dashboard/)"
                    }
                }
            },
            "error": {
                "type": "final",
                "meta": {
                    "test": {
                        "action": "await page.click('button[type=\"submit\"]')",
                        "assertion": "await expect(page.locator('.error-message')).toContainText('Invalid')"
                    }
                }
            }
        }
    }
    
    # Template 2: Form Submission
    form_template = {
        "initial": "empty",
        "states": {
            "empty": {
                "on": {"START_FILL": "filling"},
                "meta": {
                    "test": {
                        "action": "await page.goto('YOUR_FORM_URL')",
                        "assertion": "await expect(page.locator('form')).toBeVisible()"
                    }
                }
            },
            "filling": {
                "on": {
                    "VALIDATE_VALID": "valid",
                    "VALIDATE_INVALID": "invalid"
                },
                "meta": {
                    "test": {
                        "action": "await page.fill('input[name=\"name\"]', 'Test User')",
                        "assertion": "await expect(page.locator('input[name=\"name\"]')).toHaveValue('Test User')"
                    }
                }
            },
            "valid": {
                "on": {"SUBMIT": "success"},
                "meta": {
                    "test": {
                        "action": "// All validations pass",
                        "assertion": "await expect(page.locator('.submit-button')).toBeEnabled()"
                    }
                }
            },
            "invalid": {
                "on": {"FIX": "filling"},
                "meta": {
                    "test": {
                        "action": "// Validation errors shown",
                        "assertion": "await expect(page.locator('.error')).toBeVisible()"
                    }
                }
            },
            "success": {
                "type": "final",
                "meta": {
                    "test": {
                        "action": "await page.click('.submit-button')",
                        "assertion": "await expect(page.locator('.success-message')).toBeVisible()"
                    }
                }
            }
        }
    }
    
    # Template 3: Navigation Flow
    nav_template = {
        "initial": "home",
        "states": {
            "home": {
                "on": {
                    "GO_PRODUCTS": "products",
                    "GO_ABOUT": "about",
                    "GO_CONTACT": "contact"
                },
                "meta": {
                    "test": {
                        "action": "await page.goto('YOUR_HOME_URL')",
                        "assertion": "await expect(page.locator('h1')).toContainText('Home')"
                    }
                }
            },
            "products": {
                "on": {"GO_HOME": "home", "GO_DETAIL": "productDetail"},
                "meta": {
                    "test": {
                        "action": "await page.click('a[href=\"/products\"]')",
                        "assertion": "await expect(page).toHaveURL(/products/)"
                    }
                }
            },
            "productDetail": {
                "on": {"GO_PRODUCTS": "products", "ADD_TO_CART": "cart"},
                "meta": {
                    "test": {
                        "action": "await page.click('.product-card:first-child')",
                        "assertion": "await expect(page.locator('.product-detail')).toBeVisible()"
                    }
                }
            },
            "cart": {
                "on": {"CHECKOUT": "checkout", "CONTINUE_SHOPPING": "products"},
                "meta": {
                    "test": {
                        "action": "await page.click('.add-to-cart')",
                        "assertion": "await expect(page.locator('.cart-count')).not.toContainText('0')"
                    }
                }
            },
            "checkout": {
                "type": "final",
                "meta": {
                    "test": {
                        "action": "await page.click('.checkout-button')",
                        "assertion": "await expect(page).toHaveURL(/checkout/)"
                    }
                }
            },
            "about": {
                "on": {"GO_HOME": "home"},
                "meta": {
                    "test": {
                        "action": "await page.click('a[href=\"/about\"]')",
                        "assertion": "await expect(page).toHaveURL(/about/)"
                    }
                }
            },
            "contact": {
                "type": "final",
                "meta": {
                    "test": {
                        "action": "await page.click('a[href=\"/contact\"]')",
                        "assertion": "await expect(page).toHaveURL(/contact/)"
                    }
                }
            }
        }
    }
    
    templates_data = [
        {
            "name": "Login Flow",
            "description": "Standard login flow with success and error paths",
            "category": "authentication",
            "definition": login_template
        },
        {
            "name": "Form Submission",
            "description": "Multi-step form with validation states",
            "category": "forms",
            "definition": form_template
        },
        {
            "name": "Navigation Flow",
            "description": "Website navigation with product browsing and checkout",
            "category": "navigation",
            "definition": nav_template
        }
    ]
    
    try:
        for template_data in templates_data:
            # Check if template already exists
            existing = MBTTemplate.query.filter_by(name=template_data['name']).first()
            if not existing:
                template = MBTTemplate(**template_data)
                db.session.add(template)
                print(f"   ✅ Created template: {template_data['name']}")
            else:
                print(f"   ⏭️  Template already exists: {template_data['name']}")
        
        db.session.commit()
        print("\n✅ Sample templates created successfully!")
        
    except Exception as e:
        db.session.rollback()
        print(f"\n⚠️  Could not create templates: {e}")

def rollback():
    """Rollback the migration (drop tables)"""
    print("⚠️  Rolling back Model-Based Testing migration...")
    
    try:
        with app.app_context():
            # Drop tables
            StateMachine.__table__.drop(db.engine, checkfirst=True)
            MBTTestExecution.__table__.drop(db.engine, checkfirst=True)
            MBTTemplate.__table__.drop(db.engine, checkfirst=True)
            
            print("✅ MBT tables dropped successfully")
            return True
            
    except Exception as e:
        print(f"❌ Rollback failed: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Model-Based Testing Database Migration')
    parser.add_argument('action', choices=['migrate', 'rollback'], help='Action to perform')
    
    args = parser.parse_args()
    
    if args.action == 'migrate':
        success = migrate()
        sys.exit(0 if success else 1)
    elif args.action == 'rollback':
        success = rollback()
        sys.exit(0 if success else 1)
