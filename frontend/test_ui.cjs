const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch();
  const page = await browser.newPage();
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle2' });

  // Use the sample resume
  await page.evaluate(() => {
    const divs = Array.from(document.querySelectorAll('div'));
    const useSample = divs.find(d => d.textContent.includes('Use Sample Resume'));
    if (useSample) useSample.click();
  });
  
  await new Promise(r => setTimeout(r, 1000));

  // Fill Job URL
  await page.type('input[placeholder*="linkedin"]', 'https://careers.boozallen.com/careers/JobDetail?jobId=122540&source=JB-16500');
  
  // Click Tailor Resume
  await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const tailor = buttons.find(b => b.textContent.includes('Tailor Resume'));
    if (tailor) tailor.click();
  });

  // Wait for cache result to stream in and button to return to "Tailor Resume"
  await page.waitForFunction(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const tailor = buttons.find(b => b.textContent.includes('Tailor Resume'));
    return tailor && !tailor.disabled;
  }, { timeout: 30000 });

  await new Promise(r => setTimeout(r, 1000));

  // Click 'AI Changes' tab
  await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll('.tab'));
    const changesTab = tabs.find(t => t.textContent.includes('AI Changes'));
    if (changesTab) changesTab.click();
  });

  await new Promise(r => setTimeout(r, 500));

  // Get the HTML of the first change block
  const html = await page.evaluate(() => {
    const el = document.querySelector('div[style*="overflow: hidden"]');
    return el ? el.outerHTML : 'No element found';
  });
  
  console.log(html);

  await browser.close();
})();
