#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

// 获取当前日期和时间戳
const now = new Date();
const dateString = now.toISOString().split('T')[0].replace(/-/g, '');
const timestamp = now.getTime();

// 读取 package.json 获取版本
const packagePath = path.join(__dirname, '..', 'package.json');
const packageJson = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
const appVersion = packageJson.version;
const fullVersion = `${appVersion}-${timestamp}`;

// Service Worker 文件路径
const swPath = path.join(__dirname, '..', 'public', 'service-worker.js');
const versionPath = path.join(__dirname, '..', 'public', 'version.json');

// 读取 Service Worker 内容
let swContent = fs.readFileSync(swPath, 'utf8');

// 更新版本信息
const buildDateRegex = /const BUILD_DATE = .*?;/;
const versionRegex = /const MANUAL_VERSION = .*?;/;

swContent = swContent.replace(buildDateRegex, `const BUILD_DATE = '${dateString}';`);
swContent = swContent.replace(versionRegex, `const MANUAL_VERSION = '${fullVersion}';`);

// 写回 Service Worker 文件
fs.writeFileSync(swPath, swContent);

// 生成版本信息文件
const versionInfo = {
  version: fullVersion,
  buildDate: dateString,
  buildTime: now.toISOString(),
  appVersion: appVersion
};

fs.writeFileSync(versionPath, JSON.stringify(versionInfo, null, 2));

console.log(`✅ Service Worker 版本已更新:`);
console.log(`   构建日期: ${dateString}`);
console.log(`   应用版本: ${appVersion}`);
console.log(`   完整版本: ${fullVersion}`);
console.log(`   构建时间: ${now.toISOString()}`);
