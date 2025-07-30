document.getElementById('start').onclick = () => {
  chrome.tabs.query({active: true, currentWindow: true}, tabs => {
    chrome.tabs.sendMessage(tabs[0].id, 'start-recording');
  });
};
document.getElementById('stop').onclick = () => {
  chrome.tabs.query({active: true, currentWindow: true}, tabs => {
    chrome.tabs.sendMessage(tabs[0].id, 'stop-recording');
  });
};
document.getElementById('export').onclick = () => {
  chrome.storage.local.get('seleniumActions', data => {
    const actions = data.seleniumActions || [];
    let code = `import org.openqa.selenium.*;\nimport org.openqa.selenium.chrome.ChromeDriver;\nimport org.openqa.selenium.support.ui.WebDriverWait;\nimport org.openqa.selenium.support.ui.ExpectedConditions;\nimport java.time.Duration;\n\npublic class UITest {\n    public static void main(String[] args) {\n        WebDriver driver = new ChromeDriver();\n        WebDriverWait wait = new WebDriverWait(driver, Duration.ofSeconds(10));\n\n`;
    actions.forEach(a => {
      if (a.type === 'url') code += `        driver.get("${a.url}");\n\n`;
      else if (a.type === 'click') code += `        WebElement element = wait.until(ExpectedConditions.elementToBeClickable(By.cssSelector("${a.selector}")));\n        element.click();\n\n`;
      else if (a.type === 'input') code += `        WebElement element = wait.until(ExpectedConditions.visibilityOfElementLocated(By.cssSelector("${a.selector}")));\n        element.clear();\n        element.sendKeys("${a.value}");\n\n`;
      else if (a.type === 'select') code += `        WebElement element = wait.until(ExpectedConditions.visibilityOfElementLocated(By.cssSelector("${a.selector}")));\n        element.click();\n        element.sendKeys("${a.value}");\n\n`;
    });
    code += `        // driver.quit();\n    }\n}`;
    document.getElementById('output').textContent = code;
  });
};