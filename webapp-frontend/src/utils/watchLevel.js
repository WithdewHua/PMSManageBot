/**
 * 根据观看时长计算并返回等级图标
 * 100小时 = 1颗星星
 * 4颗星星 = 1个月亮 (400小时)
 * 4个月亮 = 1个太阳 (1600小时)
 * 4个太阳 = 1个皇冠 (6400小时)
 * 
 * @param {Number} watchedTime 观看时长（小时）
 * @param {Boolean} showEmptyText 是否在无观看记录时显示文本（默认为false）
 * @return {String} 包含图标的HTML字符串
 */
export function getWatchLevelIcons(watchedTime, showEmptyText = false) {
  const hourPerStar = 100;
  const starsPerMoon = 4;
  const moonsPerSun = 4;
  const sunsPerCrown = 4;
  
  let result = '';
  let remainingHours = watchedTime;
  
  // 计算皇冠数量
  const crownHours = hourPerStar * starsPerMoon * moonsPerSun * sunsPerCrown;
  if (remainingHours >= crownHours) {
    const crowns = Math.floor(remainingHours / crownHours);
    result += `<v-icon color="amber-darken-2" size="small" class="mr-1">mdi-crown</v-icon>`.repeat(crowns);
    remainingHours %= crownHours;
  }
  
  // 计算太阳数量
  const sunHours = hourPerStar * starsPerMoon * moonsPerSun;
  if (remainingHours >= sunHours) {
    const suns = Math.floor(remainingHours / sunHours);
    result += `<v-icon color="amber" size="small" class="mr-1">mdi-weather-sunny</v-icon>`.repeat(suns);
    remainingHours %= sunHours;
  }
  
  // 计算月亮数量
  const moonHours = hourPerStar * starsPerMoon;
  if (remainingHours >= moonHours) {
    const moons = Math.floor(remainingHours / moonHours);
    result += `<v-icon color="blue" size="small" class="mr-1">mdi-moon-waning-crescent</v-icon>`.repeat(moons);
    remainingHours %= moonHours;
  }
  
  // 计算星星数量
  if (remainingHours >= hourPerStar) {
    const stars = Math.floor(remainingHours / hourPerStar);
    result += `<v-icon color="yellow-darken-2" size="small" class="mr-1">mdi-star</v-icon>`.repeat(stars);
    remainingHours %= hourPerStar;
  }
  
  // 如果没有任何图标但有观看时间，显示一个未填充的星星
  if (result === '' && watchedTime > 0) {
    result = `<v-icon color="grey" size="small">mdi-star-outline</v-icon>`;
  } else if (result === '' && watchedTime === 0 && showEmptyText) {
    result = `<span class="text-grey">暂无观看记录</span>`;
  }
  
  return result;
}

/**
 * 生成观看等级的友好文本说明
 * 
 * @param {Number} watchedTime 观看时长（小时）
 * @return {String} 友好的等级描述文本
 */
export function getWatchLevelText(watchedTime) {
  const hourPerStar = 100;
  const starsPerMoon = 4;
  const moonsPerSun = 4;
  const sunsPerCrown = 4;
  
  let levelText = '';
  let nextMilestone = 0;
  
  // 计算当前等级和下一个里程碑
  const crownHours = hourPerStar * starsPerMoon * moonsPerSun * sunsPerCrown;
  const sunHours = hourPerStar * starsPerMoon * moonsPerSun;
  const moonHours = hourPerStar * starsPerMoon;
  
  const crowns = Math.floor(watchedTime / crownHours);
  const remainingAfterCrowns = watchedTime % crownHours;
  
  const suns = Math.floor(remainingAfterCrowns / sunHours);
  const remainingAfterSuns = remainingAfterCrowns % sunHours;
  
  const moons = Math.floor(remainingAfterSuns / moonHours);
  const remainingAfterMoons = remainingAfterSuns % moonHours;
  
  const stars = Math.floor(remainingAfterMoons / hourPerStar);
  
  if (crowns > 0) {
    levelText = `${crowns}皇冠`;
    if (suns > 0) levelText += ` ${suns}太阳`;
    if (moons > 0) levelText += ` ${moons}月亮`;
    if (stars > 0) levelText += ` ${stars}星星`;
    nextMilestone = (crowns * crownHours) + (suns * sunHours) + (moons * moonHours) + ((stars + 1) * hourPerStar);
  } else if (suns > 0) {
    levelText = `${suns}太阳`;
    if (moons > 0) levelText += ` ${moons}月亮`;
    if (stars > 0) levelText += ` ${stars}星星`;
    nextMilestone = (suns * sunHours) + (moons * moonHours) + ((stars + 1) * hourPerStar);
  } else if (moons > 0) {
    levelText = `${moons}月亮`;
    if (stars > 0) levelText += ` ${stars}星星`;
    nextMilestone = (moons * moonHours) + ((stars + 1) * hourPerStar);
  } else if (stars > 0) {
    levelText = `${stars}星星`;
    nextMilestone = ((stars + 1) * hourPerStar);
  } else {
    levelText = '新手';
    nextMilestone = hourPerStar;
  }
  
  const hoursToNext = nextMilestone - watchedTime;
  
  return {
    levelText,
    nextMilestone,
    hoursToNext: hoursToNext > 0 ? hoursToNext.toFixed(2) : 0
  };
}