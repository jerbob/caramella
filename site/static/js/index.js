var app = new Vue({
  el: '#app',
  delimiters: ['[[', ']]'],
  data: {
    players: []
  },
  methods: {
    readable: function(seconds) {
      seconds = parseInt(seconds);
      segments = [];
      [minutes, seconds] = divmod(seconds, 60);
      [hours, minutes] = divmod(minutes, 60);
      [days, hours] = divmod(hours, 24);
      measures = {day: days, hour: hours, minute: minutes, second: seconds}
      for (const [name, value] of Object.entries(measures)) {
        if (value > 1) {
          segments.push(value + ' ' + name + 's')
        } else if (value == 1) {
          segments.push('1 ' + name)
        }
      }
      return segments.join(', ')
    }
  }
})

window.setInterval(
  function() {
    app.players.forEach(
      function(player) {
        if (player.listening) {
          player.score += 1
        }
      }
    )
  }, 1000
)

function divmod(y, x) {
  var quotient = Math.floor(y/x);
  var remainder = y % x;
  return [quotient, remainder]
}

fetch('https://api.caramella.ml/scores').then(
  (response) => {return response.json()}
).then((data) => {
  app.players = [];
  data.forEach(
    player => player.name ? app.players.push(player) : null
  );
})
