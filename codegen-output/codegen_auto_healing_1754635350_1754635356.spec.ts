const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    headless: false
  });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto('https://staging-accounts.upgrad.dev/?redirect=https://staging-link.upgrad.dev/?redirectUrl=https://stage-lxp.upgrad.dev/identity');
  await page.getByText('Proceed with Email').first().click();
  await page.getByText('Proceed with Phone').click();
  await page.close();

  // ---------------------
  await context.close();
  await browser.close();
})();