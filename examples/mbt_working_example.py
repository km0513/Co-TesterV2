"""
Model-Based Testing - Working Example
Demonstrates the complete MBT workflow with the login flow example
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.mbt_test_generator import MBTTestGenerator
from utils.ai_state_discovery import AIStateMachineDiscovery
import json

# Note: Generator is instantiated per machine, discovery can be reused
ai_discovery = AIStateMachineDiscovery()

def print_section(title):
    """Print a formatted section header"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def example_1_basic_test_generation():
    """Example 1: Generate tests from a login state machine"""
    print_section("Example 1: Basic Test Generation")
    
    # Define a login flow state machine
    login_machine = {
        "initial": "idle",
        "states": {
            "idle": {
                "on": {
                    "FILL_VALID": "validInput",
                    "FILL_INVALID": "invalidInput"
                },
                "meta": {
                    "test": {
                        "action": "await page.goto('https://example.com/login')",
                        "assertion": "await expect(page.locator('#email')).toBeVisible()"
                    }
                }
            },
            "validInput": {
                "on": {
                    "SUBMIT": "success"
                },
                "meta": {
                    "test": {
                        "action": "await page.fill('#email', 'valid@example.com'); await page.fill('#password', 'password123');",
                        "assertion": "await expect(page.locator('button[type=\"submit\"]')).toBeEnabled()"
                    }
                }
            },
            "invalidInput": {
                "on": {
                    "SUBMIT": "error"
                },
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
                        "assertion": "await expect(page.locator('.error-message')).toContainText('Invalid credentials')"
                    }
                }
            }
        }
    }
    
    print("\n📋 State Machine Definition:")
    print(json.dumps(login_machine, indent=2))
    
    # Create generator for this machine
    generator = MBTTestGenerator(login_machine)
    
    # Get coverage info
    print("\n📊 Coverage Information:")
    coverage = generator.get_coverage_info()
    print(f"  • Total States: {coverage['total_states']}")
    print(f"  • Total Transitions: {coverage['total_transitions']}")
    print(f"  • Final States: {coverage['final_states']}")
    
    # Calculate test paths (shortest)
    print("\n🗺️ Test Paths (Shortest Strategy):")
    shortest_paths = generator.calculate_test_paths('shortest')
    for i, path in enumerate(shortest_paths, 1):
        print(f"\n  Path {i}:")
        for j, state in enumerate(path):
            if j < len(path) - 1:
                print(f"    {state} →", end=" ")
            else:
                print(f"{state}")
    
    # Calculate test paths (all paths)
    print("\n🗺️ Test Paths (All Paths Strategy):")
    all_paths = generator.calculate_test_paths('all')
    print(f"  Total unique paths: {len(all_paths)}")
    for i, path in enumerate(all_paths, 1):
        print(f"\n  Path {i}:")
        for j, state in enumerate(path):
            if j < len(path) - 1:
                print(f"    {state} →", end=" ")
            else:
                print(f"{state}")
    
    # Calculate test paths (edge coverage)
    print("\n🗺️ Test Paths (Edge Coverage Strategy):")
    edge_paths = generator.calculate_test_paths('edge')
    print(f"  Paths for 100% transition coverage: {len(edge_paths)}")
    
    # Generate XState machine code
    print("\n💻 Generated XState Machine (TypeScript):")
    xstate_code = generator.generate_xstate_machine()
    print(xstate_code[:500] + "...\n  [truncated for display]")
    
    # Generate test model
    print("\n🧪 Generated Test Model:")
    test_model = generator.generate_test_model()
    print(test_model[:500] + "...\n  [truncated for display]")
    
    # Generate complete test suite
    print("\n✅ Generated Test Suite:")
    test_suite = generator.generate_test_suite('https://example.com/login')
    print(test_suite[:500] + "...\n  [truncated for display]")
    
    print("\n✨ Success! All test files would be generated")
    print("    (Call generator.generate_all_files() to create actual files)")

def example_2_validation():
    """Example 2: Validate state machine structure"""
    print_section("Example 2: State Machine Validation")
    
    print("\n⚠️ Note: Validation requires AI Discovery utility (Gemini API key)")
    print("   Set GEMINI_API_KEY environment variable to enable validation")
    print("\n   Validation checks:")
    print("   • Initial state exists")
    print("   • No unreachable states")
    print("   • All states have assertions")
    print("   • Final states are defined")
    print("   • No dead-end states")

def example_3_ai_recording_analysis():
    """Example 3: Convert Codegen recording to state machine"""
    print_section("Example 3: AI Recording Analysis")
    
    # Simulated Codegen recording
    recording_actions = [
        {
            "type": "goto",
            "url": "https://example.com/login",
            "timestamp": "2025-01-01T10:00:00"
        },
        {
            "type": "fill",
            "selector": "#email",
            "value": "user@example.com",
            "timestamp": "2025-01-01T10:00:05"
        },
        {
            "type": "fill",
            "selector": "#password",
            "value": "password123",
            "timestamp": "2025-01-01T10:00:10"
        },
        {
            "type": "click",
            "selector": "button[type='submit']",
            "timestamp": "2025-01-01T10:00:15"
        },
        {
            "type": "waitForNavigation",
            "url": "https://example.com/dashboard",
            "timestamp": "2025-01-01T10:00:20"
        }
    ]
    
    print("\n📹 Codegen Recording:")
    print(json.dumps(recording_actions, indent=2))
    
    print("\n🤖 Note: AI analysis requires Gemini API key")
    print("   Set GEMINI_API_KEY environment variable to enable")
    print("   The AI would analyze these actions and generate a state machine")
    print("\n   Example output would include:")
    print("   • Identified states: pageLoad, formFilling, submitting, authenticated")
    print("   • Suggested transitions: LOAD → FILL → SUBMIT → SUCCESS")
    print("   • Meta assertions for each state")

def example_4_e2e_workflow():
    """Example 4: Complete end-to-end workflow"""
    print_section("Example 4: Complete E2E Workflow")
    
    print("\n📝 Complete MBT Workflow Steps:")
    print("\n1️⃣ Define State Machine")
    print("   • Use UI to create/edit machine")
    print("   • Or use AI to generate from URL/recording")
    
    print("\n2️⃣ Validate Structure")
    print("   • Check for unreachable states")
    print("   • Verify all states have assertions")
    print("   • Ensure proper initial/final states")
    
    print("\n3️⃣ Calculate Test Paths")
    print("   • Choose strategy: shortest, all, or edge")
    print("   • Shortest: Fast, covers all states")
    print("   • All: Comprehensive, every possible path")
    print("   • Edge: 100% transition coverage")
    
    print("\n4️⃣ Generate Test Code")
    print("   • Create XState machine (.ts)")
    print("   • Create test model (.ts)")
    print("   • Create Playwright tests (.spec.ts)")
    
    print("\n5️⃣ Execute Tests")
    print("   • Run with Playwright test runner")
    print("   • Collect coverage metrics")
    print("   • Track state/transition coverage")
    
    print("\n6️⃣ Iterate & Improve")
    print("   • Use AI to suggest missing states")
    print("   • Update machine based on app changes")
    print("   • Re-generate tests automatically")

def example_5_shopping_cart():
    """Example 5: E-commerce shopping cart flow"""
    print_section("Example 5: Shopping Cart State Machine")
    
    shopping_cart_machine = {
        "initial": "empty",
        "states": {
            "empty": {
                "on": {"ADD_ITEM": "hasItems"},
                "meta": {
                    "test": {
                        "action": "await page.goto('https://shop.example.com')",
                        "assertion": "await expect(page.locator('.cart-count')).toContainText('0')"
                    }
                }
            },
            "hasItems": {
                "on": {
                    "ADD_ITEM": "hasItems",
                    "REMOVE_ITEM": "empty",
                    "CHECKOUT": "checkout"
                },
                "meta": {
                    "test": {
                        "action": "await page.click('.add-to-cart')",
                        "assertion": "await expect(page.locator('.cart-count')).not.toContainText('0')"
                    }
                }
            },
            "checkout": {
                "on": {
                    "FILL_SHIPPING": "shippingComplete",
                    "CANCEL": "hasItems"
                },
                "meta": {
                    "test": {
                        "action": "await page.click('.checkout-button')",
                        "assertion": "await expect(page.locator('h1')).toContainText('Checkout')"
                    }
                }
            },
            "shippingComplete": {
                "on": {
                    "FILL_PAYMENT": "paymentComplete",
                    "BACK": "checkout"
                },
                "meta": {
                    "test": {
                        "action": "await page.fill('#address', '123 Main St')",
                        "assertion": "await expect(page.locator('.next-step')).toBeEnabled()"
                    }
                }
            },
            "paymentComplete": {
                "on": {"PLACE_ORDER": "orderSuccess"},
                "meta": {
                    "test": {
                        "action": "await page.fill('#card', '4111111111111111')",
                        "assertion": "await expect(page.locator('.place-order')).toBeVisible()"
                    }
                }
            },
            "orderSuccess": {
                "type": "final",
                "meta": {
                    "test": {
                        "action": "await page.click('.place-order')",
                        "assertion": "await expect(page.locator('.success-message')).toBeVisible()"
                    }
                }
            }
        }
    }
    
    print("\n🛒 Shopping Cart State Machine:")
    print(json.dumps(shopping_cart_machine, indent=2))
    
    generator = MBTTestGenerator(shopping_cart_machine)
    coverage = generator.get_coverage_info()
    print(f"\n📊 Coverage: {coverage['total_states']} states, {coverage['total_transitions']} transitions")
    
    paths = generator.calculate_test_paths('shortest')
    print(f"\n🗺️ Shortest Paths: {len(paths)} path(s) to cover all states")

def main():
    """Run all examples"""
    print("\n" + "="*80)
    print(" MODEL-BASED TESTING - WORKING EXAMPLES")
    print("="*80)
    
    try:
        example_1_basic_test_generation()
        example_2_validation()
        example_3_ai_recording_analysis()
        example_4_e2e_workflow()
        example_5_shopping_cart()
        
        print_section("✅ All Examples Completed Successfully!")
        print("\n🚀 Next Steps:")
        print("   1. Run this script: python examples/mbt_working_example.py")
        print("   2. Start Flask app and visit: http://localhost:5000/mbt")
        print("   3. Create your first state machine in the UI")
        print("   4. Generate and run tests!")
        print("\n📚 Documentation:")
        print("   • Full spec: docs/model-based-testing-implementation.md")
        print("   • Quick start: docs/MBT-QUICKSTART.md")
        print("\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
