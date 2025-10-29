# 🎯 Model-Based Testing - Practical Guide

## What is Model-Based Testing (MBT)?

**Simple Explanation**: Instead of writing 50 individual test files, you create ONE model (state machine) that describes how your app works, and it automatically generates all the tests for you.

### Traditional Testing (Manual)
```
❌ Write test: user logs in successfully
❌ Write test: user enters wrong password
❌ Write test: user enters invalid email
❌ Write test: user clicks forgot password
❌ Write test: ... 45 more scenarios
```
**Result**: 50 test files, 2 days of work

### Model-Based Testing (Smart)
```
✅ Create one state machine with 5 states
✅ Click "Generate Tests" button
✅ Get all 50 test scenarios automatically
```
**Result**: 1 model, 15 minutes of work

---

## 📖 Real-World Example: Testing a Login Page

Let's test a login page step-by-step.

### Step 1: Understand Your App

Your login page has these scenarios:
1. User visits login page (sees form)
2. User fills valid credentials → Success (goes to dashboard)
3. User fills invalid credentials → Error message shown
4. User leaves fields empty → Validation error

### Step 2: Draw the State Machine (On Paper)

```
┌─────────┐
│  IDLE   │ ← User lands on login page
│ (Start) │
└────┬────┘
     │
     ├─── FILL_VALID ──────► ┌──────────────┐
     │                       │ VALID_INPUT  │ ← Fields filled correctly
     │                       └──────┬───────┘
     │                              │
     │                              SUBMIT
     │                              │
     │                              ▼
     │                       ┌──────────┐
     │                       │ SUCCESS  │ ← Redirected to dashboard
     │                       │ (Final)  │
     │                       └──────────┘
     │
     └─── FILL_INVALID ─────► ┌──────────────┐
                              │ INVALID_INPUT│ ← Wrong credentials
                              └──────┬───────┘
                                     │
                                     SUBMIT
                                     │
                                     ▼
                              ┌──────────┐
                              │  ERROR   │ ← Error message shown
                              │ (Final)  │
                              └──────────┘
```

### Step 3: Convert to JSON

```json
{
  "initial": "idle",
  "states": {
    "idle": {
      "on": {
        "FILL_VALID": "validInput",
        "FILL_INVALID": "invalidInput"
      },
      "meta": {
        "test": {
          "action": "await page.goto('https://myapp.com/login')",
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
          "action": "await page.fill('#email', 'user@example.com'); await page.fill('#password', 'ValidPass123');",
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
          "action": "await page.fill('#email', 'wrong'); await page.fill('#password', '123');",
          "assertion": "await expect(page.locator('.error-hint')).toBeVisible()"
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
```

### Step 4: Use the UI to Create It

1. **Start the app**:
   ```bash
   python app.py
   ```

2. **Visit**: http://localhost:5000/mbt

3. **Click "Create New" tab**

4. **Click "Load Login Flow Example"** (pre-fills the form)

5. **Or paste your JSON** into the editor

6. **Click "Validate"** to check for errors

7. **Click "Create Machine"** to save

### Step 5: Generate Tests

Now the magic happens! The tool will generate:

**Path 1**: `idle → validInput → success` (Happy path)
- User enters valid credentials and logs in

**Path 2**: `idle → invalidInput → error` (Error path)
- User enters invalid credentials and sees error

**Path 3**: `idle` only (Page load test)
- User just visits the login page

### Step 6: Get the Generated Code

Click **"Generate Tests"** button, and you get 3 TypeScript files:

#### `loginMachine.machine.ts`
```typescript
import { createMachine } from 'xstate';

export const loginMachine = createMachine({
  id: 'loginMachine',
  initial: 'idle',
  states: {
    idle: { /* ... */ },
    validInput: { /* ... */ },
    invalidInput: { /* ... */ },
    success: { type: 'final' },
    error: { type: 'final' }
  }
});
```

#### `loginMachine.testModel.ts`
```typescript
import { createModel } from '@xstate/test';
import { loginMachine } from './loginMachine';

const testModel = createModel(loginMachine);
export default testModel;
```

#### `loginMachine.spec.ts`
```typescript
import { test } from '@playwright/test';
import testModel from './testModel';

test.describe('Login Flow - Model-based Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('https://myapp.com/login');
  });

  // Auto-generated tests for all paths
  const testPlans = testModel.getShortestPathPlans();
  
  for (const plan of testPlans) {
    for (const path of plan.paths) {
      test(path.description, async ({ page }) => {
        // Executes: idle → validInput → success
        // OR: idle → invalidInput → error
        // All paths covered automatically!
      });
    }
  }
});
```

### Step 7: Run the Tests

```bash
npx playwright test loginMachine.spec.ts
```

**Result**: All login scenarios tested automatically! 🎉

---

## 🎯 When to Use MBT

### ✅ Perfect For:

**1. User Flows** (Multi-step processes)
- Login/Signup flows
- Checkout processes
- Multi-step forms
- Wizards/onboarding

**2. State-Heavy UIs**
- Modals that open/close
- Tabs that switch
- Filters that change content
- Drag-and-drop interfaces

**3. Complex Navigation**
- Website navigation (Home → Products → Details → Cart)
- App navigation with many screens
- Back/forward button testing

**4. Form Validations**
- Multiple validation states
- Required/optional fields
- Error messages
- Success states

### ❌ Not Ideal For:

- Simple CRUD operations (just write a regular test)
- One-off UI checks (faster to write manual test)
- Visual regression testing (use Percy/Chromatic)
- API testing (use Postman/REST client)

---

## 🚀 Quick Start Workflow

### Option A: Start from Scratch (Your Own App)

**1. Identify the flow to test** (e.g., checkout process)

**2. List all states**:
- Cart empty
- Cart has items
- Shipping info entered
- Payment info entered
- Order confirmed

**3. List all transitions** (events):
- ADD_ITEM
- REMOVE_ITEM
- ENTER_SHIPPING
- ENTER_PAYMENT
- PLACE_ORDER

**4. Add test assertions for each state**:
- Empty cart: "Cart is empty" message visible
- Has items: Item count shows "1 item"
- Shipping: Address form visible
- Payment: Card input visible
- Confirmed: "Thank you" message visible

**5. Create the JSON** (see example above)

**6. Use the UI** at http://localhost:5000/mbt to:
   - Create the machine
   - Validate it
   - Generate tests
   - Run tests

### Option B: Use AI to Generate (Fastest)

**1. Visit the "AI Tools" tab** in the UI

**2. Paste your app URL**: `https://myapp.com/login`

**3. AI generates the state machine** for you automatically!

**4. Review and edit** if needed

**5. Generate tests**

---

## 📊 Test Strategies Explained

### Strategy 1: Shortest Path (Recommended for Most Cases)
**What it does**: Finds the fastest way to reach each state

**Example for login**:
- Path 1: `idle` (just load page)
- Path 2: `idle → validInput` (fill form)
- Path 3: `idle → validInput → success` (complete login)
- Path 4: `idle → invalidInput` (fill wrong)
- Path 5: `idle → invalidInput → error` (see error)

**Use when**: You want fast tests that cover all states

### Strategy 2: All Paths (Most Thorough)
**What it does**: Tests EVERY possible combination

**Example for login**:
- All shortest paths PLUS
- `idle → validInput → invalidInput` (change mind)
- `idle → invalidInput → validInput` (fix mistake)
- Every possible route

**Use when**: Critical flows (payment, security)

### Strategy 3: Edge Coverage (Balance)
**What it does**: Ensures every transition is tested at least once

**Use when**: You want thorough coverage without too many tests

---

## 🎨 Real Examples by Scenario

### Example 1: E-commerce Checkout (6 States)

```json
{
  "initial": "cartEmpty",
  "states": {
    "cartEmpty": {
      "on": { "ADD_ITEM": "cartHasItems" },
      "meta": {
        "test": {
          "action": "await page.goto('/cart')",
          "assertion": "await expect(page.locator('.empty-cart')).toBeVisible()"
        }
      }
    },
    "cartHasItems": {
      "on": { 
        "CHECKOUT": "shipping",
        "REMOVE_ALL": "cartEmpty"
      },
      "meta": {
        "test": {
          "action": "await page.click('.add-to-cart')",
          "assertion": "await expect(page.locator('.cart-count')).toContainText('1')"
        }
      }
    },
    "shipping": {
      "on": { "NEXT": "payment" },
      "meta": {
        "test": {
          "action": "await page.fill('#address', '123 Main St')",
          "assertion": "await expect(page.locator('.shipping-form')).toBeVisible()"
        }
      }
    },
    "payment": {
      "on": { "SUBMIT": "confirmed" },
      "meta": {
        "test": {
          "action": "await page.fill('#card', '4111111111111111')",
          "assertion": "await expect(page.locator('.payment-form')).toBeVisible()"
        }
      }
    },
    "confirmed": {
      "type": "final",
      "meta": {
        "test": {
          "action": "await page.click('.place-order')",
          "assertion": "await expect(page.locator('.success')).toBeVisible()"
        }
      }
    }
  }
}
```

**What you get**: Complete checkout testing with 10+ test scenarios

### Example 2: Tab Navigation (4 States)

```json
{
  "initial": "homeTab",
  "states": {
    "homeTab": {
      "on": {
        "CLICK_PRODUCTS": "productsTab",
        "CLICK_ABOUT": "aboutTab",
        "CLICK_CONTACT": "contactTab"
      },
      "meta": {
        "test": {
          "action": "await page.goto('/')",
          "assertion": "await expect(page.locator('[aria-selected=\"true\"]')).toContainText('Home')"
        }
      }
    },
    "productsTab": {
      "on": { "CLICK_HOME": "homeTab" },
      "meta": {
        "test": {
          "action": "await page.click('a[href=\"/products\"]')",
          "assertion": "await expect(page).toHaveURL(/products/)"
        }
      }
    },
    "aboutTab": {
      "on": { "CLICK_HOME": "homeTab" },
      "meta": {
        "test": {
          "action": "await page.click('a[href=\"/about\"]')",
          "assertion": "await expect(page).toHaveURL(/about/)"
        }
      }
    },
    "contactTab": {
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
```

**What you get**: All tab combinations tested automatically

---

## 💡 Best Practices

### 1. Start Simple
Don't try to model your entire app. Start with ONE flow:
- ✅ Good: "Login flow" (5 states)
- ❌ Too much: "Entire app" (50 states)

### 2. Use Templates
The UI has 3 pre-built templates:
- Login Flow
- Form Submission
- Navigation Flow

Copy one and modify it for your app!

### 3. Name States Clearly
- ✅ Good: `cartHasItems`, `shippingComplete`, `paymentEntered`
- ❌ Bad: `state1`, `state2`, `state3`

### 4. Add Good Assertions
Each state should verify the UI is correct:
```javascript
"meta": {
  "test": {
    "action": "what to do to reach this state",
    "assertion": "how to verify we're in this state"
  }
}
```

### 5. Test Incrementally
1. Create machine with 2-3 states
2. Generate tests and run them
3. Add more states gradually
4. Re-generate tests

---

## 🎬 Complete Tutorial Video Script

**Minute 1**: "Hi! I'll show you how to test a login page in 5 minutes using Model-Based Testing."

**Minute 2**: "First, I draw my login flow on paper: Idle → Valid Input → Success. And Idle → Invalid Input → Error."

**Minute 3**: "I open http://localhost:5000/mbt, click Create New, and load the Login example."

**Minute 4**: "I click Generate Tests, and boom - I get 3 TypeScript files with all my test scenarios!"

**Minute 5**: "I run `npx playwright test` and all my login tests pass. That's it!"

---

## 📚 Cheat Sheet

### Quick Reference

**State Machine Structure**:
```json
{
  "initial": "firstState",
  "states": {
    "stateName": {
      "on": { "EVENT": "nextState" },
      "meta": {
        "test": {
          "action": "playwright action",
          "assertion": "playwright assertion"
        }
      }
    },
    "finalState": {
      "type": "final"
    }
  }
}
```

**Common Events**:
- `CLICK` - User clicks button
- `FILL` - User fills form
- `SUBMIT` - User submits
- `CANCEL` - User cancels
- `NEXT` / `BACK` - Navigation
- `SUCCESS` / `ERROR` - Results

**Common Assertions**:
- `toBeVisible()` - Element shows
- `toHaveURL()` - URL changed
- `toContainText()` - Text present
- `toBeEnabled()` - Button enabled
- `toHaveValue()` - Input has value

---

## ❓ FAQ

### Q: Do I need to know XState?
**A**: No! The tool generates XState code for you. Just focus on defining states.

### Q: Can I use this with my existing tests?
**A**: Yes! MBT-generated tests work alongside your manual tests.

### Q: How do I update tests when my app changes?
**A**: Update the state machine JSON, click "Generate Tests" again. Done!

### Q: Can AI really generate state machines?
**A**: Yes! Give it a URL and it suggests states. You review and edit.

### Q: What if my app is too complex?
**A**: Break it into smaller flows. Model one feature at a time.

---

## 🚀 Next Steps

**Now**: Try the login example
1. Run: `python app.py`
2. Visit: http://localhost:5000/mbt
3. Click "Create New" → "Load Login Flow Example"
4. Click "Create Machine"
5. Click "Generate Tests" (coming soon in UI)

**Next**: Model your own app's login
1. Copy the login JSON
2. Change URLs to your app
3. Update selectors (`#email` → your selector)
4. Generate and run!

**Advanced**: Use AI tools
1. Set Gemini API key: `$env:GEMINI_API_KEY="your-key"`
2. Use "AI Tools" tab
3. Paste your URL
4. Get state machine automatically

---

## 💬 Still Confused?

**Think of it this way**:

Traditional testing = Writing a recipe for every meal separately
- Recipe for breakfast
- Recipe for lunch  
- Recipe for dinner
- Recipe for snacks

Model-Based Testing = Writing a cookbook with rules
- List all ingredients (states)
- List all cooking methods (transitions)
- Tool generates all possible meals (tests) automatically

**You define the ingredients once, get infinite recipes!** 🍳

---

**Questions?** Check the other docs:
- `docs/MBT-COMPLETE-README.md` - Full technical guide
- `docs/MBT-QUICKSTART.md` - Quick start
- `examples/mbt_working_example.py` - Code examples
