function update_address_book(){
  $.ajax({
      dataType: "json",
      url: "/stargate/get/address_book",
      data: {
          type: "all"
      },
      success: function( json ) {
          summary = json['summary']
          addresses = json['address_book']
          galaxy_path = json['galaxy_path']
          load_address_book()
      },
      error: function (){
          console.log("Failed to load Address Book from Stargate")
      }
  });
}
function load_address_book(){
    $("#address_book_summary").html('')
    nameLookup = {
      "fan": "Subspace Gates",
      "lan": "LAN Gates",
      "standard": "Standard Gates",
    }
    $.each(summary, function( name, count) {
        $("#address_book_summary").append("<span>" + count + " "+ nameLookup[name] + "</span>")
    });
    $.each(addresses, function( index, value ) {
        address_raw = value.gate_address
        address_string = address_raw.join("-");
        is_gate_online = value.is_gate_online
        if (is_gate_online == 0){
                is_gate_online = ""
        } else {is_gate_online = "Online"}
        $.each(address_raw, function( index, value) {
            value=("000" + value).substr(-3,3);
            address_raw[index] = '<img src="chevrons/'+galaxy_path+'/'+value+'.svg" />';
        });
        address = address_raw.join("");
        $("#presets").append('<div onclick="window.location = \'index.htm?address=' +
          address_string + '\';">' + value.name + address + is_gate_online + '</div>' );
    });
}
