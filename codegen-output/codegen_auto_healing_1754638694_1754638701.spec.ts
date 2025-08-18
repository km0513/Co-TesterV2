const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    headless: false
  });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto('https://staging-accounts.upgrad.dev/?redirect=https://staging-link.upgrad.dev/?redirectUrl=https://stage-lxp.upgrad.dev/identity');
  await page.getByRole('textbox', { name: 'Mobile Number' }).click();
  await page.getByText('Proceed with Email').first().click();
  await page.getByRole('textbox', { name: 'Email Address' }).fill('r');
  await page.getByRole('textbox', { name: 'Email Address' }).click();
  await page.getByRole('textbox', { name: 'Email Address' }).fill('ramesh.rao@upgrad.com');
  await page.getByRole('button', { name: 'CONTINUE' }).click();
  await page.close();

  // ---------------------
  await context.close();
  await browser.close();
})();