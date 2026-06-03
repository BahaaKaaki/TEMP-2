#!/usr/bin/env node
/**
 * Browser automation script: Navigate to app, find Qual Creator, create new chat.
 * Requires login first. Set TEST_EMAIL and TEST_PASSWORD env vars to auto-login.
 * Run: TEST_EMAIL=user@example.com TEST_PASSWORD=xxx node browser-steps.mjs
 */
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const screenshotsDir = path.join(__dirname, 'browser-screenshots');
const TEST_EMAIL = process.env.TEST_EMAIL;
const TEST_PASSWORD = process.env.TEST_PASSWORD;

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  const steps = [];

  try {
    // Step 1: Navigate and screenshot
    await page.goto('http://localhost:5173/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.screenshot({ path: path.join(screenshotsDir, '01-initial-page.png'), fullPage: true });
    steps.push('Step 1: Navigated to http://localhost:5173/ and took screenshot');

    // Login if credentials provided and we see login form
    const signInBtn = page.locator('button:has-text("Sign in"), button:has-text("Signing in")');
    if (await signInBtn.count() > 0 && TEST_EMAIL && TEST_PASSWORD) {
      await page.fill('input[name="email"], input[type="email"]', TEST_EMAIL);
      await page.fill('input[name="password"], input[type="password"]', TEST_PASSWORD);
      await signInBtn.click();
      await page.waitForTimeout(3000);
      await page.screenshot({ path: path.join(screenshotsDir, '01b-after-login.png'), fullPage: true });
      steps.push('Step 1b: Logged in with provided credentials');
    } else if (await signInBtn.count() > 0) {
      steps.push('Step 1b: Login required - set TEST_EMAIL and TEST_PASSWORD to auto-login. Skipping Qual Creator steps.');
      await browser.close();
      console.log('\n--- Summary ---\n' + steps.join('\n'));
      return;
    }

    // Step 2: Find and click Qual Creator (workflow in left sidebar)
    await page.waitForSelector('text=Workflow Chats', { timeout: 5000 }).catch(() => null);
    const qualCreator = page.locator('button:has-text("Qual Creator"), span:has-text("Qual Creator")').first();
    const count = await qualCreator.count();
    if (count === 0) {
      // List all workflow names visible
      const workflowButtons = page.locator('button:has(span.flex-1)');
      const names = await workflowButtons.evaluateAll(els => els.map(e => e.textContent?.trim()).filter(Boolean));
      steps.push('Step 2: "Qual Creator" not found. Available workflows: ' + (names.length ? names.join(', ') : '(none or still loading)'));
      // Click first workflow if Qual Creator not found (for demo)
      if (names.length > 0) {
        await workflowButtons.first().click();
        await page.waitForTimeout(1500);
        await page.screenshot({ path: path.join(screenshotsDir, '02-first-workflow-expanded.png'), fullPage: true });
        steps.push('Step 2b: Expanded first workflow instead: ' + names[0]);
      }
    } else {
      await qualCreator.click();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: path.join(screenshotsDir, '02-qual-creator-expanded.png'), fullPage: true });
      steps.push('Step 2: Clicked Qual Creator and expanded it');
    }

    // Step 3: Find and click New Chat button
    const newChatBtn = page.locator('text=New chat').or(page.locator('button:has-text("+")')).first();
    if (await newChatBtn.count() > 0) {
      await newChatBtn.click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(screenshotsDir, '03-new-chat-modal.png'), fullPage: true });
      steps.push('Step 3: Clicked New chat button');
    } else {
      steps.push('Step 3: New chat button not found');
    }

    // Step 4: Fill modal and confirm (if modal appeared)
    const createBtn = page.locator('button:has-text("Create Chat")').or(page.locator('button:has-text("Create")')).first();
    if (await createBtn.count() > 0) {
      const input = page.locator('input[type="text"]').first();
      if (await input.count() > 0) {
        await input.fill('Test Chat - ' + new Date().toISOString().slice(0, 19));
      }
      await createBtn.click();
      await page.waitForTimeout(1000);
      await page.screenshot({ path: path.join(screenshotsDir, '04-chat-created.png'), fullPage: true });
      steps.push('Step 4: Filled modal and clicked Create Chat');
    } else {
      steps.push('Step 4: Create Chat button not found (modal may not have opened)');
    }

  } catch (err) {
    steps.push('Error: ' + err.message);
    await page.screenshot({ path: path.join(screenshotsDir, 'error.png'), fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n--- Summary ---\n' + steps.join('\n'));
}

import fs from 'fs';
if (!fs.existsSync(screenshotsDir)) fs.mkdirSync(screenshotsDir, { recursive: true });
main();
