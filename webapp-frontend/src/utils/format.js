/**
 * 格式化字节数为可读的流量单位
 * @param {number} bytes - 字节数
 * @param {number} decimals - 小数位数，默认为2
 * @returns {string} 格式化后的流量字符串
 */
export function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 B';
  
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

/**
 * 格式化流量数据，针对大于 1GB 的数据显示为 GB，小于的显示为 MB
 * @param {number} bytes - 字节数
 * @returns {string} 格式化后的流量字符串
 */
export function formatTraffic(bytes) {
  if (bytes === 0) return '0 MB';
  
  const gb = bytes / (1024 * 1024 * 1024);
  const mb = bytes / (1024 * 1024);
  
  if (gb >= 1) {
    return gb.toFixed(2) + ' GB';
  } else {
    return mb.toFixed(1) + ' MB';
  }
}
